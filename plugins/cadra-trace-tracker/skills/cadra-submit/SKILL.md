<!-- plugins/cadra-trace-tracker/skills/cadra-submit/SKILL.md -->
---
description: Submit this workspace's Claude Code work sessions to Cadra for assessment. Use when the user says "submit my trace", "save my work to Cadra", "send my session", "sync my traces", or wants to make sure their assessment work is recorded.
---

# Skill: cadra-submit
**Plugin:** cadra-trace-tracker

## Purpose

Collect the sessions run in this workspace, convert and redact them, and submit
them to Cadra with a server-confirmed receipt.

## Preconditions

The workspace must be connected (`.cadra/config.json` present). If it is not, run
the cadra-connect skill instead.

## Steps

1. Run the submit script and capture ALL output:

   ```
   python "$CLAUDE_PLUGIN_ROOT/scripts/cadra_submit.py" --workspace "<WORKSPACE>"
   ```

2. Report the result in plain language:
   - `FOUND n session(s)` → how many sessions were found for this workspace. Say
     the number even when it is zero.
   - `SUBMITTED` lines → how many sessions were sent, and the server's confirmed
     message count. This is the server's receipt, not a local claim.
   - `SKIP` lines → already submitted and unchanged.
   - `NOTE` lines → transcripts that were examined and left out, with the reason
     the script gave: started in a sibling directory, or carrying no recorded
     working directory. Report only those reasons. Mention that starting `claude`
     from the workspace root keeps future sessions in scope.
   - `FAILED` lines → say which session failed and why in one sentence, followed
     by any `HINT` line the script printed. Common cases: no internet (retry
     later, nothing is lost); an unaccepted token (re-run cadra-connect with a
     fresh one); `rejected_revoked` or `rejected_expired` (contact the program
     team); `binding_mismatch` (this workspace's git remote differs from the one
     registered).
   - "Everything is already submitted" → say exactly that.

3. If the user asks what was sent, point them at `.cadra/last-preview.json`, which
   records each session's messages exactly as submitted, the directories it
   visited, and how many secrets were redacted.

## Rules

- Always run the script. Never claim work is submitted without a server receipt.
- Never print the token.
- Only sessions started in this workspace or below it are collected. A session
  started in a directory *above* the workspace is out of scope and is not
  detected at all — see design §6.1. Do not tell the user such sessions were
  found or reported.
- The current session's final turns are not included — the transcript is written
  as the session progresses. Mention this only if the user asks.
