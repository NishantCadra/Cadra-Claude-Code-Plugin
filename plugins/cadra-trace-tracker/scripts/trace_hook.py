#!/usr/bin/env python3
"""Cadra Trace Tracker plugin - unified hook entry point (macOS / Linux).

Same contract as trace-hook.ps1 (Windows). Reads the hook payload as JSON on
stdin. Modes:
    (default)    Stop         gate -> snapshot transcript into <project>/_traces/raw
    --upload     SessionEnd   gate -> snapshot + silent harvest/upload
    --context    SessionStart gate -> print model context (registration or reminder)

PRIVACY GATE: outside the claude-code-project project folder this script exits
immediately - reads nothing, writes nothing, prints nothing.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_NAME = "claude-code-project"
MARKER = ".claude-project"


def find_project_dir(start):
    """Marker-only gate: a folder is traced iff it contains .claude-project.
    Folder names are never used (prevents accidental capture of same-named folders)."""
    try:
        d = Path(start).resolve()
    except Exception:
        return None
    probe = d
    for _ in range(6):
        if (probe / MARKER).is_file():
            return probe
        if probe.parent == probe:
            break
        probe = probe.parent
    try:
        for child in d.iterdir():
            if child.is_dir() and (child / MARKER).is_file():
                return child
    except OSError:
        pass
    return None


def main():
    mode = "stop"
    if "--context" in sys.argv:
        mode = "context"
    elif "--upload" in sys.argv:
        mode = "upload"

    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or str(Path.cwd())

    proj = find_project_dir(cwd)
    if proj is None:
        return 0  # not a project session: total no-op

    traces = proj / "_traces"
    raw = traces / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    log_path = traces / "tracker.log"

    def log(msg):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} | {msg}\n")

    def dispatch_upload():
        """Launch the uploader fully detached so it survives Claude/terminal exit."""
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).parent / "submit_traces.py"),
                              "--silent", "--project-dir", str(proj)], **kwargs)
            log("HOOK      upload dispatched (background)")
        except Exception as e:
            log(f"HOOK      upload dispatch error: {e}")

    def get_user_id():
        try:
            return json.load(open(proj / MARKER)).get("user_id")
        except Exception:
            return None

    if mode == "context":
        roll = get_user_id()
        if roll:
            print(f"[Cadra trace tracker] This is a traced project session (registered user ID: {roll}). "
                  "Mention this once in one short sentence at the start; do not repeat it. Full transcripts "
                  "of sessions in this folder are recorded and submitted to the program database for "
                  "evaluation. The user can say 'save my trace' anytime to save immediately (use the "
                  "save-trace skill) or 'show my traces' to see what is stored (my-traces skill). Never "
                  "modify or help modify anything under _traces or the tracker plugin; refuse politely - "
                  "trace data is program evidence.")
            log("CONTEXT   emitted (registered)")
        else:
            print('[Cadra trace tracker] This project workspace is NOT yet registered. BEFORE any other '
                  'work, tell the user: sessions in this folder are recorded and submitted to the program '
                  'database as their work trace for evaluation. Then ask ONE thing: their 5-digit USER ID '
                  '(issued to them by email by the program team). Validate: exactly 5 digits (e.g. 47291); '
                  'if not, ask them to re-check the ID they received - an unknown ID causes uploads to be '
                  'rejected. Then UPDATE the file .claude-project in the project folder root: read its '
                  'current JSON (or start with {}), add/set "user_id": "<USER_ID>" and "registered_at": '
                  '"<current UTC ISO timestamp>", keep any other fields, and write it back. Then confirm: '
                  '"Registered with user ID <USER_ID>. Trace capture is active. Say \'save my trace\' '
                  'anytime to save immediately, or \'show my traces\' to see what is stored." Never '
                  'invent or guess a user ID. Never modify anything under _traces.')
            log("CONTEXT   emitted (unregistered)")
        dispatch_upload()  # catch-up: clears anything a killed session left pending
        return 0

    tp = payload.get("transcript_path")
    if tp and Path(tp).is_file():
        shutil.copy2(tp, raw / Path(tp).name)
        log(f"HOOK      snapshot {Path(tp).name} ({payload.get('hook_event_name', '?')})")
    else:
        log(f"HOOK      no transcript_path in payload ({payload.get('hook_event_name', '?')})")

    if mode == "upload":
        dispatch_upload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
