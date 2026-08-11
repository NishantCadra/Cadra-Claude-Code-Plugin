---
description: Show the user which of their work sessions are saved in the program database. Use when the user says "show my traces", "what traces are saved", "what have I submitted", "is my work saved", "list my sessions", "check my saved chats", or wants to confirm their work is recorded.
---

# Skill: my-traces
**Plugin:** cadra-trace-tracker

## Purpose

Read-only view of the user's OWN saved traces, straight from the program database — a simple flow of which chats have been saved, plus anything still queued locally. Shows metadata only (titles, dates, turn counts); it never downloads or displays transcript content.

## Preconditions

Must run from inside a traced workspace (folder containing `.claude-project`) that is registered (`user_id` present in `.claude-project`). If unregistered, offer registration instead.

## Steps

1. Run the list command and capture output. Try python3 first, PowerShell on Windows:
   ```
   python3 "$CLAUDE_PLUGIN_ROOT/scripts/submit_traces.py" --project-dir "<workspace path>" --list
   ```
   or:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "%CLAUDE_PLUGIN_ROOT%\scripts\submit-traces.ps1" -ProjectDir "<workspace path>" -List
   ```

2. Render each saved session as a one-line STORY, newest first, so the user can recognize their work sessions at a glance. The command output gives you, per session: time span, project, turn count, the message the session BEGAN with, and the message it ENDED with. Present like:

   > **Mon 11 Aug, 09:57–10:03** · 39 turns · began *"hi"* → ended *"submit my trace"* ✓ saved

   IMPORTANT: never present the opening message alone as if it were the whole session — a session that began with "hi" still contains ALL turns up to its end; the begin → end pair plus the turn count is what shows the full span is stored. If the user seems unsure whether later work was captured, say explicitly: the entire transcript from first to last message is in the database, and the turn count proves it.

   - For each `[PENDING]` line: note it as "captured locally, not yet saved" and suggest "say 'save my trace' to save them now".
   - If the list is empty: say no sessions are saved yet and explain saving happens automatically at session end or on "save my trace".

3. Keep it compact — this is a status glance, not a report. No analysis, no transcript content.

## Rules

- Show only what the command returns — never fabricate or guess entries.
- If the database is unreachable, say so and fall back to describing the local `_traces/sent` and `_traces/pending` folders as best-effort local state.
- This skill is read-only: never trigger uploads from it (point the user to "save my trace" instead).
