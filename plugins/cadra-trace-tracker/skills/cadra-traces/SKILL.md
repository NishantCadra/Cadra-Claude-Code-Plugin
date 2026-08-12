<!-- plugins/cadra-trace-tracker/skills/cadra-traces/SKILL.md -->
---
description: Show which of the user's work sessions Cadra has stored. Use when the user says "show my traces", "what have I submitted", "is my work saved", or "list my Cadra sessions".
---

# Skill: cadra-traces
**Plugin:** cadra-trace-tracker

## Purpose

Read-only view of what the server actually holds. Never uploads anything.

## Steps

1. Run:

   ```
   python "$CLAUDE_PLUGIN_ROOT/scripts/cadra_traces.py" --workspace "<WORKSPACE>"
   ```

2. Render one compact line per stored session — date, message count, size. Keep it
   a status glance, not a report. Never show transcript content.
3. If the output says `UNAVAILABLE`, say the server could not be reached and do
   not guess from local files.
4. If nothing is stored, say so and suggest "submit my trace".

## Rules

- Read-only. Never trigger a submission from this skill — point at cadra-submit.
- Show only what the command returned; never invent entries.
- Never print the token.
