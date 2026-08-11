<!-- plugins/cadra-trace-tracker/skills/cadra-connect/SKILL.md -->
---
description: Connect this workspace to a Cadra assessment so work sessions can be submitted. Use when the user says "connect to Cadra", "set up my assessment", "register my workspace", "my Cadra token is wrong", or when cadra-submit reports the workspace is not connected.
---

# Skill: cadra-connect
**Plugin:** cadra-trace-tracker

## Purpose

Register this workspace against a Cadra coding assessment and prove the token
works immediately — so a bad token surfaces on day one rather than at the
deadline.

## Steps

1. Ask the user for the **assessment token** from their Cadra Setup page, and for
   the **proxy URL** shown alongside it (default `https://proxy.cadra.info`).
2. Confirm the workspace: the current working directory should be the root of the
   solution repository. If the user is in a subdirectory, ask before proceeding.
3. Run the connect script from the workspace root:

   ```
   python "$CLAUDE_PLUGIN_ROOT/scripts/cadra_connect.py" --token "<TOKEN>" --workspace "<WORKSPACE>" --proxy "<PROXY_URL>"
   ```

4. Report the result in plain language. On `CONNECTED`, tell the user trace
   submission is ready and they can say "submit my trace" whenever they want to
   send their work. On `FAILED`, relay the reason and what to do about it.

## Rules

- **Never print, echo, or repeat the token** in your replies.
- Never write `.cadra/config.json` yourself — always run the script, which also
  updates `.gitignore` in the correct order so the token cannot be committed.
- If the script reports failure, nothing was saved; do not claim the workspace is
  connected.
