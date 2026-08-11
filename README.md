# Cadra Trace Tracker — Claude Code Plugin

Automatic, privacy-gated capture of Claude Code work sessions for program
evaluation. Sessions run inside a registered project workspace are recorded as
full prompt traces and submitted to the Cadra program database — with zero
manual effort in the steady state. Everything outside the workspace is never
touched.

## How it works

```
Claude Code session (inside workspace)
        │  hooks: SessionStart / Stop / SessionEnd
        ▼
.claude-project marker?  ──no──▶  total no-op (nothing read, written, or sent)
        │ yes
        ▼
snapshot transcript → _traces/raw → envelope (images stripped) → _traces/pending
        │
        ▼
upload to program database (validated RPC: unknown user IDs rejected,
server-stamped timestamps, upsert on session growth, analytics meta derived)
        │
        ▼
_traces/sent + server-verified receipt
```

**The `.claude-project` file is the entire contract.** Its presence in a folder
makes that folder a traced workspace; after registration it also holds the
user's ID. No folder-name matching, no other configuration. Delete-proofing,
tamper refusal, and disclosure are enforced via session context injected at
start.

**Two reliability layers:**

- **Hooks (automatic, best-effort):** every response is snapshotted; session
  end and session start dispatch background uploads with offline queue + retry.
- **`save-trace` skill (user-triggered, authoritative):** the user says
  *"save my trace"* anytime — foreground upload, then the server itself is
  asked which sessions exist, and the user gets a verified receipt.

## User experience

1. Install the plugin (two commands, below).
2. Get the project workspace folder (shared separately as a git repo/zip).
3. Open a terminal in the folder, run `claude`. First session: Claude explains
   that work here is recorded and asks for the **5-digit user ID** issued to
   the user by email. That's the entire setup.
4. Work normally. Traces submit automatically at session end.

Useful phrases inside the workspace:

| Say | What happens |
|---|---|
| `save my trace` | Immediate submission with database-confirmed receipt |
| `show my traces` | List of saved sessions (dates, titles, turns) + anything pending |
| `my user id is wrong` | Re-registration with confirmation |

## Install

```
claude plugin marketplace add https://github.com/NishantCadra/Cadra-Claude-Code-Plugin
claude plugin install cadra-trace-tracker@cadra
```

Updates ship via `claude plugin marketplace update cadra` followed by reinstall
(or `claude plugin update`). Windows, macOS, and Linux are supported — hook
commands try `python3` first and fall back to PowerShell on Windows.

## Privacy model

- **Scope:** only sessions run from a folder containing `.claude-project` are
  captured. Personal sessions, other projects, and the rest of the machine are
  never read. A folder without the marker produces zero activity — no logs, no
  files, no network.
- **Disclosure:** every traced session announces it is being recorded, once,
  at session start.
- **Minimisation:** pasted images are stripped before upload. The shipped
  database key can only call the validated submit/list endpoints — it cannot
  read other users' data, update, or delete anything.
- **Transparency:** everything captured sits readable on the user's own disk
  (`_traces/`) before and after upload; `_traces/tracker.log` records every
  capture decision; `show my traces` reflects the server's actual state.
- **Identity:** the user types a 5-digit ID once. Names/emails live only in
  the server-side roster; the server validates every upload against it and
  stamps identity and time itself.

## Repository layout

```
.claude-plugin/marketplace.json          marketplace listing
plugins/cadra-trace-tracker/
  .claude-plugin/plugin.json             plugin manifest
  hooks/hooks.json                       SessionStart / Stop / SessionEnd wiring
  scripts/trace_hook.py|trace-hook.ps1   gate + snapshot + context + dispatch
  scripts/submit_traces.py|-traces.ps1   harvest, upload, verify, --list
  skills/register-user/                  one-question registration
  skills/save-trace/                     verified on-demand submission
  skills/my-traces/                      read-only saved-sessions view
TESTING.md                               two-tester validation guide
```

## Versioning

| Branch | State |
|---|---|
| `main` | Current release (v2.2.1): skills + hooks, single-marker identity |
| `v2.0-hooks-only` | Previous release: hooks-only capture, pre-skills |

Trace data is program evidence. Do not modify the plugin, the workspace's
`_traces/` contents, or the `.claude-project` file (beyond registration) —
tampering is treated as misconduct.
