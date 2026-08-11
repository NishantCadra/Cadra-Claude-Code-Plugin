#!/usr/bin/env python3
"""Cadra Trace Tracker - harvest + upload (macOS / Linux).

Same contract as submit-traces.ps1 (Windows): scans Claude Code session
storage (~/.claude/projects) plus the project's _traces/raw snapshots for
project-related transcripts, builds envelopes (with image payloads stripped),
and submits them to the program database via the validated RPC (server checks
the roll number against the roster and upserts).

Usage:
    python3 submit_traces.py                    interactive (first run asks roll number)
    python3 submit_traces.py --silent           hook mode: no prompts ever
    python3 submit_traces.py --scan-only        harvest but do not upload
    python3 submit_traces.py --project-dir P    explicit project folder
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SUPABASE_URL = "https://pyrpzlppjmejlohiqoyc.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB5cnB6bHBwam1lamxvaGlxb3ljIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjQ5MjM1NzcsImV4cCI6MjA4MDQ5OTU3N30.wREHqbUvRhBZoeN4IxPMZVc27FfYeFQNMysKQ7icy0I"
RPC = "tracker_submit_session_staging"
PROJECT_NAME = "claude-code-project"
MARKER = ".cowork-project"
CAPTURE_VERSION = "1.0.0-plugin"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_project_dir():
    probe = Path.cwd().resolve()
    for _ in range(4):
        if probe.name == PROJECT_NAME or (probe / MARKER).is_file():
            return probe
        if probe.parent == probe:
            break
        probe = probe.parent
    return None


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


def upload(row):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{RPC}",
        data=json.dumps({"p": row}).encode("utf-8"),
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return "uploaded" if 200 <= resp.status < 300 else f"http_{resp.status}"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        return f"http_{e.code}:{detail}"
    except Exception as e:
        return f"network_error:{type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--project-dir", default=None)
    args = ap.parse_args()

    proj = Path(args.project_dir).resolve() if args.project_dir else find_project_dir()
    if proj is None or not proj.is_dir():
        if args.silent:
            return 0
        print(f"Could not find the {PROJECT_NAME} project folder from here. Run this from inside the folder.")
        return 1

    traces = proj / "_traces"
    pending, sent, raw = traces / "pending", traces / "sent", traces / "raw"
    for d in (pending, sent, raw):
        d.mkdir(parents=True, exist_ok=True)
    log_path = traces / "tracker.log"

    # single-flight lock: another uploader running in the last 2 minutes wins
    import time
    lock = traces / "upload.lock"
    if lock.is_file() and (time.time() - lock.stat().st_mtime) < 120:
        return 0
    lock.write_text(str(now_iso()))

    def log(msg):
        line = f"{now_iso()} | {msg}"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if not args.silent:
            print(line)

    # ---- identity
    id_path = traces / "identity.json"
    if id_path.is_file():
        roll = json.load(open(id_path)).get("roll_no")
    else:
        if args.silent:
            return 0
        print("\n=== First-time setup ===")
        print("Your user ID is checked against the official program roster")
        print("when traces are uploaded - a wrong user ID will be REJECTED.")
        roll = ""
        while not (roll.isdigit() and len(roll) == 5):
            roll = input("Enter your 5-digit user ID (issued to you by email, e.g. 47291): ").strip()
        json.dump({"roll_no": roll, "activated_at": now_iso()}, open(id_path, "w"))
        log(f"IDENTITY  roll {roll} saved")
    log(f"RUN START roll={roll} scanonly={args.scan_only}")

    # ---- harvest
    state_path = traces / "state.json"
    state = {}
    if state_path.is_file():
        try:
            state = json.load(open(state_path))
        except Exception:
            state = {}

    roots = [Path.home() / ".claude" / "projects", raw]
    files = []
    for r in roots:
        if r.is_dir():
            files.extend(sorted(r.rglob("*.jsonl")))
    log(f"SCAN      {len(files)} transcript file(s) found")

    found = new = 0
    for f in files:
        dir_match = PROJECT_NAME in f.parent.name or f.parent == raw
        if not dir_match:
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                    if not any(PROJECT_NAME in line for line in fh):
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
        return 0

    # ---- upload
    ok = failed = 0
    for f in sorted(pending.glob("*.json")):
        try:
            envelope = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            log(f"FAILED    {f.name} -> unreadable envelope: {e}")
            failed += 1
            continue
        row = {k: envelope.get(k) for k in (
            "session_id", "roll_no", "title", "started_at", "ended_at", "client_captured_at",
            "turn_count", "envelope_version", "capture_version", "plugin_hash", "hook_event", "transcript")}
        outcome = upload(row)
        if outcome == "uploaded":
            f.replace(sent / f.name)
            log(f"UPLOADED  {f.name}")
            ok += 1
        else:
            log(f"FAILED    {f.name} -> {outcome}")
            failed += 1
    log(f"DONE      {ok} uploaded/confirmed, {failed} failed, {found} project session(s) known in total")
    try:
        lock.unlink()
    except OSError:
        pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
