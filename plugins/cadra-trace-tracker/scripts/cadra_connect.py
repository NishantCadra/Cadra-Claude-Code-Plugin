"""cadra-connect — register this workspace for trace submission (spec §5.1).

Exercises the token on day zero. A managed OpenCode candidate discovers a bad
token on their first prompt; a BYO candidate would otherwise discover it at
submission, after the work is done.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cadra import client, config
from cadra.repo import git_remote, strip_credentials  # noqa: F401

TIMEOUT_S = 20


def verify_token(*, proxy_base_url: str, token: str) -> tuple[bool, str]:
    """Call GET /v1/traces. The signal is 200 vs 401; contents are irrelevant."""
    request = urllib.request.Request(
        f"{proxy_base_url.rstrip('/')}/v1/traces",
        headers={"Authorization": f"Bearer {token}"}, method="GET",
    )
    try:
        # Same opener as client.py: no redirect may carry the bearer elsewhere.
        with client._OPENER.open(request, timeout=TIMEOUT_S) as resp:
            return (200 <= resp.status < 300), ""
    except urllib.error.HTTPError as err:
        if err.code == 401:
            return False, "the server did not accept this token (401)"
        return False, f"the server returned HTTP {err.code}"
    except Exception as exc:
        return False, f"could not reach Cadra ({type(exc).__name__})"


TOKEN_FILENAME = "token.txt"


def token_path(workspace: Path) -> Path:
    return config.config_dir(workspace) / TOKEN_FILENAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--init", action="store_true",
                        help="prepare .cadra/ and print where to paste the token")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"FAILED: {workspace} is not a directory")
        return 1
    # A workspace that is the home directory or a drive root would make every
    # project folder beneath it "in scope" — the candidate's whole transcript
    # store, which §6.1.1 exists to keep out.
    if workspace == Path.home().resolve() or workspace == workspace.parent:
        print(f"FAILED: {workspace} is too broad to be a project. Connect from "
              "the folder holding your solution.")
        return 1

    if args.init:
        # Create the folder and its ignore entry BEFORE the candidate pastes
        # anything, so the token file cannot exist un-ignored even briefly.
        config.ensure_gitignored(workspace)
        config.config_dir(workspace).mkdir(parents=True, exist_ok=True)
        print(f"READY paste your assessment token into {token_path(workspace)} "
              "and save the file, then say 'connect' again.")
        return 0

    source = token_path(workspace)
    try:
        token = source.read_text(encoding="utf-8").strip()
    except OSError:
        print(f"FAILED: no token file at {source}. Run with --init first, then "
              "paste your token into that file yourself.")
        return 1
    if not token:
        print(f"FAILED: {source} is empty. Paste your assessment token into it.")
        return 1

    try:
        claims = config.decode_claims(token)
    except ValueError as exc:
        print(f"FAILED: {exc}. Re-copy the token from your Setup page.")
        return 1
    if not claims.get("coding_assessment_id"):
        print("FAILED: this token carries no assessment. Re-copy it from Setup.")
        return 1
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        print("FAILED: this token has expired. Request a fresh one.")
        return 1

    proxy = args.proxy or claims.get("proxy_base_url") or ""
    if not proxy.startswith("https://"):
        print("FAILED: the proxy address must be an https:// URL. Nothing was saved.")
        return 1

    ok, detail = verify_token(proxy_base_url=proxy, token=token)
    if not ok:
        print(f"FAILED: {detail}. Nothing was saved.")
        return 1

    config.save(workspace, {
        "token": token,
        "assessment_label": args.label,
        "workspace_root": str(workspace).replace("\\", "/"),
        "git_remote": git_remote(workspace),
        "proxy_base_url": proxy.rstrip("/"),
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    # The paste file has done its job. Two plaintext copies of the token is one
    # more than necessary, and this one has no 0600 mode.
    try:
        source.unlink()
    except OSError:
        print(f"NOTE could not remove {source}; delete it yourself.")
    print(f"CONNECTED workspace={workspace}")
    print("Trace submission is ready. Say 'submit my trace' when you want to send "
          "your work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
