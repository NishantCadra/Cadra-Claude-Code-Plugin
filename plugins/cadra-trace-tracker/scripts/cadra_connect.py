"""cadra-connect — register this workspace for trace submission (spec §5.1).

Exercises the token on day zero. A managed OpenCode candidate discovers a bad
token on their first prompt; a BYO candidate would otherwise discover it at
submission, after the work is done.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cadra import config

TIMEOUT_S = 20


def git_remote(workspace: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    remote = out.stdout.strip()
    return remote or None


def verify_token(*, proxy_base_url: str, token: str) -> tuple[bool, str]:
    """Call GET /v1/traces. The signal is 200 vs 401; contents are irrelevant."""
    request = urllib.request.Request(
        f"{proxy_base_url.rstrip('/')}/v1/traces",
        headers={"Authorization": f"Bearer {token}"}, method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
            return (200 <= resp.status < 300), ""
    except urllib.error.HTTPError as err:
        if err.code == 401:
            return False, "the server did not accept this token (401)"
        return False, f"the server returned HTTP {err.code}"
    except Exception as exc:
        return False, f"could not reach Cadra ({type(exc).__name__})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"FAILED: {workspace} is not a directory")
        return 1

    try:
        claims = config.decode_claims(args.token)
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

    ok, detail = verify_token(proxy_base_url=args.proxy, token=args.token)
    if not ok:
        print(f"FAILED: {detail}. Nothing was saved.")
        return 1

    config.save(workspace, {
        "token": args.token,
        "assessment_label": args.label,
        "workspace_root": str(workspace).replace("\\", "/"),
        "git_remote": git_remote(workspace),
        "proxy_base_url": args.proxy.rstrip("/"),
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    print(f"CONNECTED workspace={workspace}")
    print("Trace submission is ready. Say 'submit my trace' when you want to send "
          "your work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
