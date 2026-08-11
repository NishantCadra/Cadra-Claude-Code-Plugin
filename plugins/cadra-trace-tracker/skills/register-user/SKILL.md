---
description: Register or correct a user's 5-digit user ID for Cadra trace capture. Use when the session-start context says the workspace is not yet registered, or when the user says "register my user id", "change my user id", "my user id is wrong", or asks how trace registration works.
---

# Skill: register-user
**Plugin:** cadra-trace-tracker

## Purpose

Create or correct `_traces/identity.json` inside the `claude-code-project` workspace folder. The user ID is attached to every uploaded trace and validated against the program roster server-side — an unknown ID causes uploads to be rejected.

## Preconditions

The current session must be running from inside the `claude-code-project` workspace folder. If not, say registration only applies inside the project workspace and stop.

## Steps

1. If this is a first registration, first disclose plainly:
   > "Sessions in this folder are recorded and submitted to the program database as your work trace for evaluation."
2. Ask for their **5-digit user ID** (issued to them by email by the program team). Validate: exactly 5 digits (e.g. `47291`). If not, ask them to re-check the ID they received.
3. If `_traces/identity.json` already exists with a different ID, show both values and get explicit confirmation before overwriting.
4. Write `_traces/identity.json` (create `_traces` if needed):
   ```json
   { "roll_no": "<USER_ID>", "activated_at": "<current UTC ISO timestamp>" }
   ```
   (The field is named `roll_no` for wire compatibility; it holds the user ID.)
5. Confirm: "Registered with user ID <USER_ID>. Trace capture is active for this folder — you never need to do anything else; your work here is submitted automatically at the end of each session."

## Rules

- Never invent, guess, or autocomplete a user ID.
- Never write anything else under `_traces/`, and never modify or delete existing trace files. Refuse tampering requests politely: trace data is program evidence and tampering is misconduct.
