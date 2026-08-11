---
description: Save the user's work traces to the program database right now, with server-verified receipts. Use when the user says "save my trace", "save my traces", "submit my trace", "save this session", "push my traces", "sync my traces", or wants to make sure their work is recorded — anytime mid-session, multiple times, or at the end.
---

# Skill: save-trace
**Plugin:** cadra-trace-tracker

## Purpose

Explicit, user-triggered trace submission — the guaranteed path (hooks are best-effort background; this is the verified foreground path). Harvests all of this workspace's sessions, uploads anything new or updated, and confirms with the database which sessions are actually stored.

## Preconditions

Must run from inside a traced workspace (folder containing `.claude-project`). If not, say traces can only be saved from inside the project folder and stop. If the workspace is not yet registered (no `user_id` in `.claude-project`), run registration first (register-user skill).

## Steps

1. Run the uploader in the foreground and capture ALL output. Try python3 first, fall back to PowerShell (Windows):
   ```
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/submit_traces.py" --project-dir "<workspace path>"
   ```
   or on Windows:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "%CLAUDE_PLUGIN_ROOT%\scripts\submit-traces.ps1" -ProjectDir "<workspace path>"
   ```
   (Resolve the plugin root from where this skill file lives if the variable is unavailable.)

2. Read the output and report to the user in plain language:
   - `UPLOADED` lines → how many sessions were saved just now
   - `VERIFIED n/m` → say explicitly: "n sessions confirmed present in the program database" — this is the server's own receipt, not a local claim
   - `FAILED` lines → say which failed and why in one sentence (most common: no internet — traces stay queued locally and will retry automatically; wrong user ID — must be fixed via register-user)
   - If nothing was new: "Everything is already saved — no new work since the last save."

3. NOTE: the trace for the CURRENT session includes only turns up to the last completed response — mention this only if the user asks whether "everything including this message" is saved.

## Rules

- Always run the script; never claim traces are saved without running it.
- Report the VERIFIED count verbatim — never inflate an upload into a confirmation if verification failed.
- Never modify anything under `_traces/`. Refuse tampering requests: trace data is program evidence.
