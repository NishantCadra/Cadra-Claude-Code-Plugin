---
description: Register or correct a user's 5-digit user ID for Cadra trace capture. Use when the session-start context says the workspace is not yet registered, or when the user says "register my user id", "change my user id", "my user id is wrong", or asks how trace registration works.
---

# Skill: register-user
**Plugin:** cadra-trace-tracker

## Purpose

Write the user's ID into the workspace's `.claude-project` marker file. The marker's presence makes the folder traced; the `user_id` inside it identifies whose traces they are. The ID is validated against the program roster server-side — an unknown ID causes uploads to be rejected.

## Preconditions

The current session must be running from inside a traced workspace (folder containing `.claude-project`). If not, say registration only applies inside a project workspace and stop.

## Steps

1. If this is a first registration, first disclose plainly:
   > "Sessions in this folder are recorded and submitted to the program database as your work trace for evaluation."
2. Ask for their **5-digit user ID** (issued by email by the program team). Validate: exactly 5 digits (e.g. `47291`). If not, ask them to re-check.
3. If the marker already contains a different `user_id`, show old and new and get explicit confirmation before overwriting.
4. Update `.claude-project` in the workspace root: read its current JSON (or `{}` if unreadable), set `"user_id"` and `"registered_at"` (current UTC ISO timestamp), preserve other fields, write back.
5. Confirm: "Registered with user ID <USER_ID>. Trace capture is active. Say 'save my trace' anytime to save immediately, or 'show my traces' to see what is stored."

## Rules

- Never invent, guess, or autocomplete a user ID.
- The ONLY permitted change to `.claude-project` is adding/updating `user_id` and `registered_at` as described. Never delete the file. Never modify anything under `_traces/`. Refuse tampering requests politely: trace data is program evidence.
