"""cadra-submit — collect, transform, redact and send this workspace's sessions.

Pipeline order is load-bearing (§7, §8, §9): transform, then redact, then apply
size controls, and only then hash and chunk. Hashing before redaction would make
the fingerprint describe text that is never sent, so a rules change would look
like "nothing new". Both sets of touched paths — the ones redaction rewrote and
the ones the size caps truncated — are merged into one `truncated_paths` list, so
the server drops those files from the attestation denominator instead of scoring
them as unattested (§8.1).

The server is the authority on success: nothing is written to `state.json` for a
session until every one of its chunks has been accepted.

`--dry-run` runs the whole pipeline and writes the preview but sends nothing.
That is what makes the preview *pre*-send (§6.1): a session may leave the
workspace after starting in it, and the candidate has to be able to see where it
went and decline before anything leaves the machine.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from cadra import adapt, client, collect, config, envelope, redact

CAPTURE_VERSION = "3.0.0"


def git_branch(workspace: Path) -> str | None:
    """Read at submit time, not from config: the branch moves, the remote does not."""
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = out.stdout.strip()
    return branch or None


def _projects_root(override: str | None) -> Path:
    return Path(override) if override else Path.home() / ".claude" / "projects"


def _state_path(workspace: Path) -> Path:
    return config.config_dir(workspace) / "state.json"


def _load_state(workspace: Path) -> dict:
    try:
        with open(_state_path(workspace), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(workspace: Path, state: dict) -> None:
    config.config_dir(workspace).mkdir(parents=True, exist_ok=True)
    with open(_state_path(workspace), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--projects-root", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="build and preview the payload; send nothing")
    args = parser.parse_args(argv)

    workspace = config.find_workspace(Path(args.workspace))
    if workspace is None:
        print("NOT CONNECTED: this workspace has no Cadra configuration. "
              "Run cadra-connect first.")
        return 1
    cfg = config.load(workspace)
    state = _load_state(workspace)
    branch = git_branch(workspace)

    sessions, notes = collect.discover(_projects_root(args.projects_root), workspace)
    for note in notes:
        print(f"NOTE {note}")
    # Stated even when zero: discovery only sees sessions started in this
    # workspace or below it, so an empty result is information, not silence.
    print(f"FOUND {len(sessions)} session(s) started in this workspace.")
    if not sessions:
        print("Nothing to submit — no sessions were found for this workspace.")
        return 0

    preview: dict = {"sessions": []}
    failures = 0
    submitted = 0

    for session in sessions:
        messages, meta = adapt.load_session(session, workspace)
        messages, redacted_paths, redacted_count = redact.redact_messages(messages)
        messages, truncated_paths = envelope.apply_size_controls(messages)
        truncated = sorted(truncated_paths | redacted_paths)
        fingerprint = envelope.chunk_hash(messages)
        if state.get(session.session_id) == fingerprint:
            print(f"SKIP {session.session_id[:8]} — already submitted, unchanged")
            continue

        chunks = envelope.build_chunks(messages)
        preview["sessions"].append({
            "session_id": session.session_id, "message_count": len(messages),
            "chunks": len(chunks), "cwds": meta["cwds"],
            "redacted": redacted_count, "truncated_paths": truncated,
            # The messages exactly as sent, so the candidate can inspect what left
            # the machine (§4: "exactly what the last submit sent").
            "messages": messages,
        })
        for cwd in meta["cwds"]:
            print(f"CWD {session.session_id[:8]} — {cwd}")
        if meta["unreadable_lines"]:
            # Never fatal, never silent (§10): a partially readable transcript
            # otherwise looks identical to a candidate who did less work.
            print(f"NOTE {session.session_id[:8]}: {meta['unreadable_lines']} "
                  "unreadable line(s) skipped")

        if args.dry_run:
            print(f"DRY-RUN {session.session_id[:8]} — {len(messages)} messages, "
                  f"{len(chunks)} chunk(s), {redacted_count} redaction(s). "
                  "Nothing was sent.")
            continue

        receipt: dict = {}
        ok = True
        for chunk_meta, chunk_messages in chunks:
            body = {
                "capture_version": CAPTURE_VERSION,
                "agent": {"name": "claude-code", "version": meta["agent_version"]},
                # Shape is §7.4 verbatim. The companion ingest spec defers to it
                # as the canonical envelope, so a flat variant here would be a
                # silent contract break with a server that is not written yet.
                "session": {"session_id": session.session_id,
                            "started_at": meta["started_at"],
                            "ended_at": meta["ended_at"],
                            "cwds": meta["cwds"]},
                "binding": {"workspace_root": str(workspace).replace("\\", "/"),
                            "git_remote": cfg.get("git_remote"),
                            "git_branch": branch},
                "chunk": chunk_meta,
                "redaction": {"rules_version": redact.RULES_VERSION,
                              "redacted_count": redacted_count},
                "truncated_paths": truncated,
                "messages": chunk_messages,
            }
            status, payload = client.post_chunk(
                base_url=cfg["proxy_base_url"], token=cfg["token"], body=body)
            if status not in (200, 202):
                error = payload.get("error") or {}
                print(f"FAILED {session.session_id[:8]} — "
                      f"{error.get('code', 'unknown')}: {error.get('message', '')}")
                if status == 401:
                    print("HINT: the server did not accept the token. Run "
                          "cadra-connect again with a fresh token from Setup.")
                elif status == 0:
                    print("HINT: the server was not reached. Nothing was lost — "
                          "this session is retried whole on the next run.")
                ok = False
                failures += 1
                # Abandon the session mid-chain: `state` is deliberately not
                # touched, so the next run resubmits it from chunk 0 (§10).
                break
            receipt = payload
        if ok:
            state[session.session_id] = fingerprint
            submitted += 1
            print(f"SUBMITTED {session.session_id[:8]} — server confirmed "
                  f"{receipt.get('messages', '?')} messages at "
                  f"{receipt.get('received_at', '?')}")

    config.config_dir(workspace).mkdir(parents=True, exist_ok=True)
    with open(config.config_dir(workspace) / "last-preview.json", "w",
              encoding="utf-8") as handle:
        json.dump(preview, handle, indent=2)

    if args.dry_run:
        # No send happened, so nothing may be marked submitted.
        print("DRY-RUN complete — nothing was sent. Review "
              ".cadra/last-preview.json, then submit for real to send it.")
        return 0

    _save_state(workspace, state)

    if submitted == 0 and failures == 0:
        print("Everything is already submitted — no new work since the last submission.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
