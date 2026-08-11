#!/usr/bin/env python3
"""Cadra Trace Tracker - harvest + upload (macOS / Linux). v2.2.0

Scans Claude Code session storage (~/.claude/projects) plus the workspace's
_traces/raw snapshots for THIS project's transcripts, builds envelopes (image
payloads stripped), and submits them via the validated RPC (server checks the
user ID against the roster and upserts).

Gate: a workspace is traced ONLY if it contains the .claude-project marker.
Folder names are irrelevant (no accidental capture of same-named folders).

Usage:
    python3 submit_traces.py --project-dir P            harvest + upload
    python3 submit_traces.py --project-dir P --silent   hook mode: no prompts
    python3 submit_traces.py --project-dir P --scan-only
    python3 submit_traces.py --project-dir P --list     list MY saved sessions from the database
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SUPABASE_URL = "https://pyrpzlppjmejlohiqoyc.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB5cnB6bHBwam1lamxvaGlxb3ljIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjQ5MjM1NzcsImV4cCI6MjA4MDQ5OTU3N30.wREHqbUvRhBZoeN4IxPMZVc27FfYeFQNMysKQ7icy0I"
RPC_SUBMIT = "tracker_submit_session_staging"
RPC_LIST = "tracker_my_sessions_staging"
MARKER = ".claude-project"
CAPTURE_VERSION = "2.2.3"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_project_dir():
    """Marker-only gate: nearest ancestor containing .claude-project."""
    probe = Path.cwd().resolve()
    for _ in range(6):
        if (probe / MARKER).is_file():
            return probe
        if probe.parent == probe:
            break
        probe = probe.parent
    return None


def encoded_dir_name(proj):
    """Claude Code encodes a session's cwd into its storage folder name by
    replacing non-alphanumerics with '-'. Compute it for THIS workspace."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(proj))


def rpc(name, payload):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{name}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def extract_text(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text", "")
    return ""


def strip_images(entries):
    for e in entries:
        m = e.get("message")
        if isinstance(m, dict) and isinstance(m.get("content"), list):
            for i, b in enumerate(m["content"]):
                if isinstance(b, dict) and b.get("type") == "image":
                    m["content"][i] = {"type": "text", "text": "[image removed before upload]"}


def parse_transcript(path):
    entries = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not entries:
        return None
    session_id = None
    for e in entries:
        session_id = e.get("sessionId") or e.get("session_id")
        if session_id:
            break
    user_ids, asst_ids = set(), set()
    first_user_text, ts_first, ts_last = None, None, None
    for e in entries:
        role = e.get("type") if e.get("type") in ("user", "assistant") else (e.get("message") or {}).get("role")
        ts = e.get("timestamp")
        if ts:
            ts_first = ts_first or ts
            ts_last = ts
        mid = ((e.get("message") or {}).get("id")) or e.get("uuid") or f"anon-{id(e)}"
        if role == "user":
            user_ids.add(mid)
            if first_user_text is None:
                first_user_text = extract_text(e.get("message") or e)
        elif role == "assistant":
            asst_ids.add(mid)
    strip_images(entries)
    title = " ".join((first_user_text or "Untitled session").split())[:120]
    return {
        "session_id": session_id or path.stem,
        "title": title,
        "started_at": ts_first,
        "ended_at": ts_last,
        "turn_count": len(user_ids) + len(asst_ids),
        "transcript": entries,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--list", action="store_true", dest="list_sessions")
    ap.add_argument("--project-dir", default=None)
    args = ap.parse_args()

    proj = Path(args.project_dir).resolve() if args.project_dir else find_project_dir()
    if proj is None or not proj.is_dir() or not (proj / MARKER).is_file():
        if args.silent:
            return 0
        print("Could not find a traced workspace (missing .claude-project marker). Run from inside your project folder.")
        return 1

    traces = proj / "_traces"
    pending, sent, raw = traces / "pending", traces / "sent", traces / "raw"
    for d in (pending, sent, raw):
        d.mkdir(parents=True, exist_ok=True)
    log_path = traces / "tracker.log"

    def log(msg):
        line = f"{now_iso()} | {msg}"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if not args.silent:
            print(line)

    # ---- identity: user_id lives in the .claude-project marker
    try:
        roll = json.load(open(proj / MARKER)).get("user_id")
    except Exception:
        roll = None
    project_name = proj.name  # auto label: the workspace folder's name, no user input
    if not roll:
        if not args.silent:
            print("This workspace is not registered yet. Start a Claude session here and it will ask for your user ID.")
        return 0

    # ---- list mode: read MY saved sessions from the database and print them
    if args.list_sessions:
        try:
            rows = rpc(RPC_LIST, {"p_code": roll}) or []
        except Exception as e:
            print(f"LIST FAILED: could not reach the database ({type(e).__name__}). Check internet and retry.")
            return 1
        local_pending = sorted(p.name for p in pending.glob("*.json"))
        print(f"SAVED SESSIONS for user {roll} ({len(rows)} in database):")
        for r in rows:
            pn = r.get("project_name") or "-"
            start = (r.get("started_at") or "")[:16]
            end = (r.get("ended_at") or "")[11:16]
            first = (r.get("title") or "").strip()[:60]
            last = (r.get("last_message") or "").strip()[:60]
            span = f"{start}-{end}" if start and end else (r.get("captured_at") or "")[:16]
            print(f"  [SAVED] {span}  {pn}  {r.get('turn_count')} turns  id={r['session_id'][:8]}")
            print(f"          began: '{first}'")
            if last and last != first:
                print(f"          ended: '{last}'")
        if local_pending:
            print(f"NOT YET SAVED ({len(local_pending)} pending locally):")
            for n in local_pending:
                print(f"  [PENDING] {n}")
        else:
            print("PENDING: none - everything captured locally has been saved.")
        return 0

    # single-flight lock
    lock = traces / "upload.lock"
    if lock.is_file() and (time.time() - lock.stat().st_mtime) < 120:
        return 0
    lock.write_text(now_iso())

    log(f"RUN START user={roll} project={project_name} scanonly={args.scan_only}")

    # ---- harvest
    state_path = traces / "state.json"
    state = {}
    if state_path.is_file():
        try:
            state = json.load(open(state_path))
        except Exception:
            state = {}

    enc = encoded_dir_name(proj)
    proj_str = str(proj)
    proj_str_esc = proj_str.replace("\\", "\\\\")

    roots = [Path.home() / ".claude" / "projects", raw]
    files = []
    for r in roots:
        if r.is_dir():
            files.extend(sorted(r.rglob("*.jsonl")))
    log(f"SCAN      {len(files)} transcript file(s) found")

    found = new = 0
    for f in files:
        # THIS workspace only: encoded-cwd dir match, our raw snapshots, or
        # content referencing this workspace's absolute path.
        dir_match = f.parent.name == enc or f.parent == raw
        if not dir_match:
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                    if not any((proj_str in line) or (proj_str_esc in line) for line in fh):
                        continue
            except OSError:
                continue
        found += 1
        parsed = parse_transcript(f)
        if parsed is None:
            continue
        env_name = f"{roll}__{parsed['session_id']}"
        src_size = f.stat().st_size
        if state.get(env_name, -1) >= src_size:
            continue
        state[env_name] = src_size
        new += 1
        envelope = {
            "envelope_version": 1, "capture_version": CAPTURE_VERSION,
            "plugin_hash": "harvester-py", "roll_no": roll,
            "project_name": project_name,
            "hook_event": "harvest", "client_captured_at": now_iso(), **parsed,
        }
        out = pending / (env_name + ".json")
        tmp = out.with_suffix(".tmp")
        json.dump(envelope, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        tmp.replace(out)
        log(f"CAPTURED  {parsed['session_id']}  turns={parsed['turn_count']}  '{parsed['title'][:60]}'")

    json.dump(state, open(state_path, "w"))
    log(f"HARVEST   {found} project session(s) found, {new} new/updated envelope(s) written")

    if args.scan_only:
        log("SCANONLY  stopping before upload.")
        try:
            lock.unlink()
        except OSError:
            pass
        return 0

    # ---- upload
    ok = failed = 0
    uploaded_ids = []
    for f in sorted(pending.glob("*.json")):
        try:
            envelope = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            log(f"FAILED    {f.name} -> unreadable envelope: {e}")
            failed += 1
            continue
        row = {k: envelope.get(k) for k in (
            "session_id", "roll_no", "project_name", "title", "started_at", "ended_at",
            "client_captured_at", "turn_count", "envelope_version", "capture_version",
            "plugin_hash", "hook_event", "transcript")}
        try:
            rpc(RPC_SUBMIT, {"p": row})
            f.replace(sent / f.name)
            log(f"UPLOADED  {f.name}")
            uploaded_ids.append(row["session_id"])
            ok += 1
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:200]
            except Exception:
                pass
            log(f"FAILED    {f.name} -> http_{e.code}:{detail}")
            failed += 1
        except Exception as e:
            log(f"FAILED    {f.name} -> network_error:{type(e).__name__}")
            failed += 1

    # ---- server-side receipt verification for this run's uploads
    if uploaded_ids:
        try:
            rows = rpc(RPC_LIST, {"p_code": roll}) or []
            in_db = {r["session_id"] for r in rows}
            verified = [s for s in uploaded_ids if s in in_db]
            missing = [s for s in uploaded_ids if s not in in_db]
            log(f"VERIFIED  {len(verified)}/{len(uploaded_ids)} of this run's uploads confirmed present in database")
            for s in missing:
                log(f"UNVERIFIED {s} - uploaded but not visible in database; will be retried next run")
        except Exception as e:
            log(f"VERIFY    could not confirm with database ({type(e).__name__}) - uploads were accepted but receipt check failed")

    log(f"DONE      {ok} uploaded, {failed} failed, {found} project session(s) known in total")
    try:
        lock.unlink()
    except OSError:
        pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
