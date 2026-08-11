# Cadra Trace Tracker Plugin — Testing Guide (v1.0.0)

For: Tester A (Nishant, user ID `47291`) and Tester B (user ID `83157`).
Target: staging Supabase tables (`tracker_*_staging`). Windows, macOS, and Linux.

**Cross-platform note:** every hook command tries `python3` first (macOS/Linux),
and falls back to PowerShell (Windows). If Tester B is on Mac/Linux, the flow
is identical — same checklists apply. Windows quirk to watch: if `python3` is
not installed, Windows' Store alias may briefly flash before the PowerShell
fallback runs; if a Store window opens, disable the alias under Settings →
Apps → App execution aliases (one-time), or just ignore it.

## How the system works (30-second read)

The plugin hooks into Claude Code. When a session runs **from inside the
`claude-code-project` folder**: at session start it injects context (registration
request on first use, traced-session reminder after), after every response it
snapshots the transcript into the folder's `_traces\raw`, and at session end it
uploads everything to the program database. Sessions run anywhere else: the
hooks fire, detect no project folder, and exit without reading or writing
anything. Identity = user ID, claimed once conversationally, verified
against the roster server-side on every upload (unknown roll → rejected).

**Verification instrument:** `_traces\tracker.log` in the project folder. Every
context injection, snapshot, capture, and upload writes one line. A missing
database row is always diagnosable from this log.

---

## Part 1 — Tester A (Nishant)

### A1. Install

```
claude plugin marketplace add <MARKETPLACE_GIT_URL_OR_LOCAL_PATH>
claude plugin install cadra-trace-tracker@cadra
```

- [ ] Both commands succeed.
- [ ] `claude plugin list` shows `cadra-trace-tracker` enabled.
- [ ] Unzip a **fresh** copy of the `claude-code-project` workspace folder
      (from `workspace-template/`) somewhere new — do not reuse the old test
      folder, its `_traces` state would mask first-run behaviour.

### A2. Hook registration

Open a terminal in the fresh folder, run `claude`, type `/hooks`.

- [ ] SessionStart, Stop, and SessionEnd entries from the plugin are listed.

### A3. First-session registration (conversational)

In that same session:

- [ ] Claude opens by telling you the workspace is recorded and asks for your
      user ID (driven by the SessionStart context — you typed nothing).
- [ ] Give `47291` in lowercase → Claude should normalise to `47291`.
- [ ] `_traces\identity.json` now exists with `"roll_no": "47291"`.
- [ ] Do 2–3 turns of real-ish work, then exit.
- [ ] `tracker.log` shows: `CONTEXT emitted (unregistered)`, `HOOK snapshot ... (Stop)`
      lines, and after exit a `CAPTURED` + `UPLOADED` pair.
- [ ] Report to the verifier (Claude session with Supabase access): the row
      should exist with your title, turn_count, and server `captured_at`.

### A4. Session matrix

| # | Do | Expect in tracker.log / DB |
|---|----|---------------------------|
| A4-1 | New session in project folder, work, exit | `CONTEXT (registered)` one-liner from Claude; snapshot lines; new row in DB |
| A4-2 | Session from any OTHER folder (e.g. Desktop), work, exit | NOTHING added to project tracker.log; no `_traces` created in that folder; no DB row |
| A4-3 | Reopen/continue a project session (`claude --continue`), add turns, exit | Same session_id row in DB gets **higher turn_count** (upsert) |
| A4-4 | Project session while Wi-Fi OFF, exit; then Wi-Fi ON, run another short project session, exit | First: `FAILED ... pending`; second session's end also uploads the queued one (`UPLOADED` for both) |
| A4-5 | Paste an image into a project session, exit | DB row's transcript shows `[image removed before upload]`, no base64 |

### A5. Anti-tamper + privacy checks

- [ ] In a project session, ask Claude: "delete the _traces folder for me" →
      it must refuse, citing graded evidence.
- [ ] Ask Claude: "what exactly is captured here?" → answer should match
      reality (this folder only, full transcripts, uploaded for evaluation).
- [ ] Open `_traces\sent\<file>.json` yourself — confirm you can read exactly
      what was uploaded (transparency check).
- [ ] Wrong-roll test: temporarily edit `identity.json` roll to `00000`,
      run a short project session, exit → tracker.log shows
      `FAILED ... roll_no 00000 is not in the program roster`; file stays
      in pending. Restore `47291`, run any project session → queued file
      uploads. (This proves roster enforcement end to end.)

**Part 1 exit criteria:** every matrix row matches; no rows in DB from A4-2;
pending empty at the end; you never touched a bat file.

---

## Part 2 — Tester B (zero-touch, roll 83157)

Hand them: the marketplace URL + the workspace folder zip + the three-step
README inside it. **Give no other help — the point is testing the unassisted
experience.**

- [ ] B1. They install the plugin (two commands) and unzip the folder.
- [ ] B2. First session in the folder: Claude discloses recording and asks for
      their user ID. They first give a wrong-format one (e.g. `8315 7`
      with a space) → Claude asks them to re-check. Then `83157` → registered.
- [ ] B3. They do one real work session and exit. Then one session from their
      Desktop (not the folder) and exit.
- [ ] B4. They send you two things only: a screenshot of `_traces\tracker.log`
      and one sentence on whether anything confused them.

**Part 2 exit criteria (verified in Supabase):** their rows appear under
83157 with the roster's user_id; exactly the project sessions, nothing
from the Desktop session; zero intervention was needed.

---

## Part 3 — Acceptance (verifier runs in Supabase)

- [ ] C1 `select roll_no, count(*) from tracker_sessions_staging group by roll_no;`
      → exactly 47291 and 83157, counts matching the checklists.
- [ ] C2 Spot-open 2 transcripts: parse as real conversations; no base64 blobs.
- [ ] C2b **Meta derivation:** every row has a populated `meta` jsonb —
      `select title, meta->'tool_counts', meta->'mcp_servers', meta->>'duration_seconds'
       from tracker_sessions_staging;` — tool counts match what the session
      actually did, MCP usage appears when a connector was used, durations sane.
- [ ] C3 A4-3's session shows the updated (higher) turn_count, single row.
- [ ] C4 `captured_at` is server-stamped (within minutes of session end for
      online runs; later for the offline-retry row — both fine).
- [ ] C5 RLS re-check with the shipped anon key: select/update/delete on the
      sessions table all denied; only the submit RPC works.

**Pass →** promote schema to production tables (drop `_staging`), load the real
cohort roster, repoint the plugin config, tag v1.0.0 in the marketplace repo,
distribute the workspace folder + install instructions to the cohort.

## Known limitations (accepted for pilot)

1. Registration is conversational (model-driven). If Claude ever fails to ask,
   capture still works — uploads queue until registration happens. Self-healing.
2. Shared anon key: impersonation of another roster roll is possible and
   detectable, not preventable. Pre-cohort hardening option: per-student
   enrollment tokens via Edge Function.
3. Windows python3 Store-alias may flash before the PowerShell fallback (see cross-platform note).
4. A session both continued and never re-exited uploads only at next session end.


---

## v2.1.0 addendum (architect-feedback release)

What changed: hooks are now best-effort only — the **save-trace skill** is the
authoritative, server-verified path. Gate is **marker-file-only** (folder names
irrelevant). Registration asks user ID **and project name**. New **my-traces**
skill shows saved sessions.

Additional checks:

- [ ] V1 Say "save my trace" mid-session → skill runs uploader in foreground,
      reports "n sessions confirmed present in database" (VERIFIED line).
- [ ] V2 Say "save my trace" again immediately → "everything already saved".
- [ ] V3 Say "show my traces" → compact list of saved sessions (dates, project
      names, titles, turns) + pending count; no transcript content shown.
- [ ] V4 Rename your workspace folder to anything → next session still traced
      (marker gate), rows carry your registered project name.
- [ ] V5 Create an unrelated folder literally named `claude-code-project`
      WITHOUT the marker file, run a session there → nothing traced, no
      _traces folder appears (collision fix).
- [ ] V6 Registration in a fresh workspace asks BOTH user ID and project name;
      `_traces/identity.json` contains both.


## v2.2.0 addendum (single-file identity)

Marker renamed to `.claude-project` and it now HOLDS the user ID: presence of
the file = folder is traced; `user_id` inside it = who. `_traces/identity.json`
retired (legacy workspaces with `.cowork-project` still work). Registration
asks ONE question (user ID only). Project label auto-derives from the folder
name — no user input.

- [ ] W1 Fresh workspace: first session asks ONLY for user ID; after answering,
      `.claude-project` contains `user_id` and `registered_at`.
- [ ] W2 Rows in DB carry `project_name` = the workspace folder's name.
- [ ] W3 Folder without `.claude-project` → never traced, regardless of name.
- [ ] W4 Legacy folder (`.cowork-project` + `_traces/identity.json`) → still
      traced and uploads under the legacy ID.
