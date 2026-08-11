# BYO trace capture — plugin design

**Date:** 2026-08-11
**Scope:** this repository only — what the Claude Code plugin collects, transforms,
redacts and submits.
**Companion spec:** the ingest route, token minting, session-state policy,
server-side redaction re-scan, attestation extraction wiring, storage and
migrations are specified separately in `cadra-prototype`
(`docs/superpowers/specs/2026-08-12-byo-trace-ingest-design.md`).
**Evidence base:** [`../cadra-integration-assessment.md`](../cadra-integration-assessment.md)
(gap register G1–G13, G5 spike) and the measurements in §8 below.

---

## 1. Purpose

Cadra assesses how a candidate builds with an AI agent. The managed path runs
OpenCode through the Cadra proxy, which observes every model call and derives the
F6 integrity evidence from it. Candidates who must work in **their own
environment** — own machine, own model key, no proxy in the loop — produce no
such evidence today.

This plugin closes that gap. It reads the transcripts Claude Code already writes,
converts them to the canonical envelope Cadra's extractor consumes, strips
secrets, and submits them to the Cadra proxy under a per-assessment token.

**Non-goal:** enforcing limits. BYO sessions are unbounded — no prompt cap, no
48-hour window, no forced model. The report marks BYO provenance rather than
pretending the constraints applied. Reconstructing a fake budget from
candidate-supplied data would be weak enforcement presented as strong.

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Skills only. No hooks.** | Consent must be an explicit act, not a background upload from a personal machine. Claude Code retains transcripts under `~/.claude/projects`, so nothing needs snapshotting as work happens. |
| D2 | **Submission authenticated by a per-assessment `f1-trace` JWT.** | Replaces the self-asserted 5-digit ID (G1). The token grants submission only — the chat route refuses it, so a BYO candidate cannot spend against Cadra's model account. |
| D3 | **No database credentials ship to candidates.** | Removes the published anon key (G2). The plugin's only network peer is the Cadra proxy. |
| D4 | **Canonical envelope = OpenAI-style `{"messages": [...]}`.** | Exactly what `proxy/attest.py` already consumes, so BYO and OpenCode traces feed one extractor. Agent-agnostic: a future Cursor/Codex client writes its own adapter and the server is untouched. |
| D5 | **The plugin owns all Claude Code format knowledge.** | Absolute-path rebasing, subagent merging, tab-numbered read results. None of it leaks into shared server code. |
| D6 | **Redaction runs client-side; the proxy re-scans.** | Secrets never leave the machine in the normal case, and a stale or tampered client cannot defeat the guarantee. |
| D7 | **All plugin state lives in `<workspace>/.cadra/`.** | Blast radius is the project directory. Nothing is written to the home directory or anywhere else. |
| D8 | **Scoping keys on the `cwd` recorded inside transcripts.** | The encoded folder name is both incomplete and over-inclusive (§6.1). |
| D9 | **Single Python implementation.** | The parallel PowerShell port caused roughly half of G13, including a missing verification step that made a shipped skill instruction unfulfillable on Windows. |

---

## 3. What is removed

The plugin is repurposed, not extended. Deleted outright:

- `hooks/hooks.json` and both hook scripts — D1.
- `scripts/submit-traces.ps1`, `scripts/trace-hook.ps1` — D9.
- All Supabase constants and RPC calls — D3.
- The `.claude-project` marker — it held a bearer token at the root of a repo the
  candidate publishes to GitHub.
- `_traces/` in the workspace: `raw/` snapshots (unnecessary without hooks),
  `pending/`, `sent/`, `state.json`, `tracker.log`.
- The `register-user`, `save-trace`, `my-traces` skills, superseded by §5.

---

## 4. Filesystem contract

```
<workspace>/
  .gitignore          ← cadra-connect appends ".cadra/" if not already present
  .cadra/
    config.json       ← token, assessment binding      (chmod 0600 on POSIX)
    state.json        ← per-session submission cursor
    last-preview.json ← exactly what the last submit sent, for inspection
```

**Invariant — enforced in review and tests:**

> The plugin writes **only** inside `<workspace>/.cadra/`, plus one append to
> `<workspace>/.gitignore` at connect time. Every other filesystem access is
> read-only.

The `.gitignore` entry is written **before** `config.json` is created, so the
token file is born ignored and cannot enter git history. The append is idempotent
and never reorders or rewrites existing entries. If `.gitignore` is absent it is
created.

**Read exception, stated explicitly:** the plugin must read
`~/.claude/projects/<encoded-cwd>/…`, because that is where Claude Code stores
transcripts and no copy exists inside the repo. The containment guarantee covers
writes, not reads.

`.cadra` must be added to `_IGNORED_DIR_PARTS` in `line_attest.py` (companion
spec) so plugin files never count toward attestation coverage.

### 4.1 `config.json`

```jsonc
{
  "token": "<f1-trace JWT>",
  "assessment_label": "Suryaa FMCG",     // display only
  "workspace_root": "C:/Dev/my-solution",
  "git_remote": "https://github.com/candidate/solution.git",
  "proxy_base_url": "https://proxy.cadra.info",
  "connected_at": "2026-08-11T09:00:00Z"
}
```

`assessment_id` is deliberately absent — the server derives it from the token.
The client never asserts identity.

---

## 5. Skills

Three skills. Each is a thin conversational wrapper: the model collects input and
reports results; a Python script does all state manipulation and I/O. The current
plugin has the model hand-write JSON into a security-critical file, which depends
on model fidelity for correctness.

### 5.1 `cadra-connect`

Triggered by "connect to Cadra", "set up my assessment", "my token is wrong".

1. Ask for the token from the Setup page. Validate shape locally (three
   dot-separated segments, decodes as JWT, `type == "f1-trace"`, unexpired).
2. Determine `workspace_root` — the current working directory, confirmed with the
   candidate. Read `git remote get-url origin` if the workspace is a git repo.
3. Run `cadra_connect.py`, which appends `.cadra/` to `.gitignore`, writes
   `config.json`, then calls `GET /v1/traces` to prove the token works.
4. Report: connected, or the specific failure (expired token, wrong assessment,
   no network).

**Why this exists.** A managed OpenCode candidate discovers a bad token on their
first prompt, within seconds. A BYO candidate would otherwise discover it at
submission — after the work is done. `cadra-connect` forces the token to be
exercised on day zero.

Re-running is supported and expected: tokens get reissued, and candidates change
machines. A re-connect that changes `git_remote` is accepted locally; the server
decides whether to flag it.

### 5.2 `cadra-submit`

Triggered by "submit my trace", "save my work", "send my session to Cadra".

1. Resolve the assessment: walk up from the cwd to the first directory containing
   `.cadra/config.json`; that directory is the workspace. Nested workspaces
   therefore resolve to the innermost one. If none is found, stop and point at
   `cadra-connect` — never guess.
2. Collect (§6), transform (§7), redact (§8), and write `last-preview.json`.
3. **Show the candidate a summary before sending**: sessions, turn counts, byte
   size, and the redaction count. This is the consent surface.
4. Submit per session, chunked (§9).
5. Report the server's receipt verbatim — never a local claim of success.

Submission is idempotent: resubmitting an unchanged session is a no-op server-side,
and a grown session replaces its predecessor.

### 5.3 `cadra-traces`

Triggered by "show my traces", "what have I submitted", "is my work saved".

Read-only. Calls `GET /v1/traces` and renders one line per stored session —
time span, turn count, size, submitted-at. Never displays transcript content, and
never triggers an upload. If the server is unreachable it says so rather than
falling back to a local guess.

---

## 6. Collection

### 6.1 Which sessions belong to the assessment

**Rule: a session belongs to the assessment iff its recorded `cwd` is
`workspace_root` or a descendant of it.** Every transcript entry carries `cwd`,
`gitBranch` and `version`, so this is read from content, never inferred from the
directory name.

The encoded folder name cannot be used, on measured evidence:

- **Incomplete.** Running `claude` from a subdirectory creates a *separate*
  project folder. `C--Dev-cadra-dev` and `C--Dev-cadra-dev-cadra-prototype` are
  two folders for one repo; matching only the workspace's own encoded name drops
  every session started from a subdirectory.
- **Over-inclusive.** The encoding maps non-alphanumerics to `-`, so prefix
  matching `C--Dev-cadra-dev` also captures a sibling `C:/Dev/cadra-dev-other`.
- **Not one-to-one.** A single folder held three unrelated cwds
  (`C:/Dev/RDI`, `C:/Dev/RDI/rdi_demo`, `C:/Dev/RDI/lakehouse-iot-platform`).

Git worktrees fall out correctly: a cwd under `<workspace>/.claude/worktrees/…`
is a descendant, so it is included.

### 6.2 Subagent transcripts

For each selected session, also read:

```
~/.claude/projects/<encoded-cwd>/<session-id>/subagents/agent-<id>.jsonl
                                              agent-<id>.meta.json
```

**This is not optional.** Across the projects surveyed there were 452 `Agent`
tool calls and **zero** `isSidechain` entries in any main transcript — subagent
work is entirely absent from it. For one RDI session that is 38.6 MB of subagent
transcript against 11 MB of main session. Including it moved `agent_share` from
0.169 to 0.414 and flipped the integrity rollup from `caution` to `ok`.

`meta.json` supplies `toolUseId`, `agentType`, `description`, `spawnDepth` and
`model` — the linkage back to the parent `Agent` call.

The old plugin's `rglob("*.jsonl")` would sweep these up as *separate anonymous
sessions with wrong IDs*, which is worse than skipping them.

### 6.3 Incremental submission

`state.json` records, per session, the byte offset and entry count last submitted.
A session is resubmitted only if it has grown. This mirrors the server's
upsert-on-growth semantics.

---

## 7. Transformation

| Claude Code | Canonical message | Notes |
|---|---|---|
| `content[].tool_use` | `assistant.tool_calls[]` → `{id, type:"function", function:{name, arguments}}` | Name preserved as emitted (`Write`); the extractor lowercases. `arguments` stays a dict. |
| `content[].tool_result` | `{role:"tool", tool_call_id, content}` | Paired by `tool_use_id`. |
| `content[].text` (assistant) | `assistant.content` | Needed for grading and message-trace. |
| `content` string (user) | `{role:"user", content}` | Candidate turns. |
| `content[].thinking` | **dropped entirely** | See §8 — the block is discarded including its `signature`. |
| images, anywhere | placeholder text | Including inside `tool_result` parts. |
| `mode`, `permission-mode`, `ai-title`, `file-history-*`, `attachment`, `queue-operation`, `agent-name`, `last-prompt` | dropped | Not conversation. |
| subagent entries | merged into `messages` by timestamp | Tagged `cadra_agent:{parent_tool_use_id, agent_type}`. |

Subagent messages are **interleaved into the same array**, not held separately, so
`attestation_items_from_payload` picks up their file writes with no server change.
The extractor reads only `role` and `tool_calls`; the `cadra_agent` key is ignored
by it and preserved in storage for grading.

### 7.1 Path rebasing

Absolute tool paths under `workspace_root` become workspace-relative with forward
slashes. Paths **outside** the workspace are deliberately left absolute, so the
server's `_GLOBAL_PATH_RE` discards them — writes outside the project should not
be attested, and this achieves it without a special case.

This is load-bearing, not cosmetic. `_GLOBAL_PATH_RE` (`line_attest.py:192`)
discards drive-letter paths, so without rebasing **every** `Write` and `Edit` is
dropped: the spike measured 50 writes and 58 edits reduced to a single attestation
item, `agent_share` 0.0, and flags `low_agent_share` + `unverified_authorship`. A
candidate whose agent wrote the entire repo would be automatically flagged for
cheating.

### 7.2 Line-number normalisation

Claude Code prefixes read results with `<n>\t`. The server's `_strip_line_numbers`
recognises `|`, `:` and `→` but not tab, so unstripped read text never hash-matches
and **zero** read events are produced — starving `foreign_code_rewritten`. The
plugin strips it, per D5. The server's own stripper is a safe no-op on
already-stripped text because its 80% threshold will not match.

### 7.3 Envelope

```jsonc
{
  "capture_version": "3.0.0",
  "agent":   { "name": "claude-code", "version": "2.0.14" },
  "session": { "session_id": "…", "started_at": "…", "ended_at": "…",
               "cwds": ["C:/Dev/ws", "C:/Dev/ws/backend"] },
  "binding": { "workspace_root": "C:/Dev/ws",
               "git_remote": "…", "git_branch": "main" },
  "chunk":   { "index": 0, "total": 2, "prefix_hash": "…", "chunk_hash": "…" },
  "redaction": { "rules_version": "1", "redacted_count": 12 },
  "truncated_paths": ["data/huge.csv"],
  "messages": [ … ]
}
```

---

## 8. Redaction

Claude Code transcripts carry the content of every `Read` and the stdout of every
`Bash` — `.env` bodies, connection strings, tokens in tool arguments. The existing
plugin redacts nothing but images, and does that incorrectly.

**Rules, versioned as `rules_version`:**

| Class | Action |
|---|---|
| `.env`-family file reads (`.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`) | Drop the tool result body entirely, keep the path |
| Token shapes (`sk-…`, `ghp_…`, `github_pat_…`, `AKIA…`, `xox[baprs]-…`, JWT triples) | Replace with `[redacted:<class>]` |
| Assignments matching `(?i)(api[_-]?key|secret|token|password|passwd|credential)\s*[=:]\s*\S+` | Redact the value, keep the key |
| High-entropy strings: ≥32 chars, single token (no whitespace), drawn from `[A-Za-z0-9+/=_-]`, Shannon entropy ≥ 4.0 bits/char, and **not** matching a known-safe shape (git SHA, UUID, content hash, data-URI payload, file path) | Replace with `[redacted:entropy]` |
| Images | `[image removed before upload]` — **including inside `tool_result` parts** |

Redaction runs **after** transformation and **before** chunking, so
`last-preview.json` is byte-identical to what is sent.

Every redaction increments `redacted_count`, surfaced in the pre-send summary. The
candidate sees "12 secrets redacted" and can inspect `last-preview.json`.

**Known limit, stated rather than papered over:** pattern-based redaction is
best-effort. A secret in an unrecognised format survives. This is why the proxy
re-scans (D6), and why the candidate preview exists.

### 8.1 Redaction vs attestation — a real conflict

Attestation works by hashing the lines the agent wrote and matching them against
the lines in the submitted repo. **Redacting content inside a `tool_use`
argument changes those lines, so they stop matching** — the file silently loses
coverage and can drag `agent_share` toward the `low_agent_share` threshold. The
candidate is then penalised for our redaction.

Rules, by location:

| Location | Redaction | Rationale |
|---|---|---|
| `tool_result` bodies | Full rules | Read output and command stdout; never hashed against the repo |
| user / assistant text | Full rules | Pasted secrets; not attestation input |
| `tool_use` write arguments (`content`, `new_string`, `edits[].new_string`) | Full rules, **and** the target path is added to `truncated_paths` | Redaction is non-negotiable, so the file is excluded from coverage instead of scoring as unattested |

Reusing `truncated_paths` is deliberate — `coding_assessment_truncated_paths` and
the `attest_truncated` bucket already exist for exactly this situation, so a
redacted file is excluded from the coverage denominator rather than counted
against the candidate.

The entropy rule is the main false-positive risk here (base64 fixtures, minified
assets), which is a further reason redaction must never silently degrade a score.

---

## 9. Size management

### 9.1 Measured

Two real projects, transcripts including subagents:

| | RDI | Aurora |
|---|---|---|
| On-disk JSONL (what today's plugin uploads) | 50.1 MB | 55.9 MB |
| Canonical envelope, no controls | ~22.2 MB | ~21.0 MB |
| Canonical envelope, controls applied | **6.34 MB** | **13.04 MB** |
| Reduction vs on-disk | 87% | 77% |
| Largest single session | 6.34 MB | 6.83 MB |

**Per-control contribution:**

| Control | RDI | Aurora | Assessment |
|---|---|---|---|
| Images → placeholder | 13.7 MB | 1.0 MB | Dominant, highly variable |
| Drop thinking blocks | 2.14 MB | 6.86 MB | Dominant |
| Tool-result 64 KB cap | 0.03 MB | 0 MB | Insurance only |
| Write 2000-line truncation | 0 MB | 0 MB | Insurance only |

### 9.2 What the numbers mean

**Most of the reduction is the transformation itself**, not any policy — dropping
non-conversation entry types and per-entry metadata takes 50 MB to 22 MB before a
single control applies.

**Thinking blocks must be dropped whole, including `signature`.** The reasoning
text measures **0.00 MB** — Claude Code does not persist it. The entire cost is
the `signature` blob, roughly 2 KB per block: 2.14 MB over 1,023 blocks in RDI and
6.86 MB over 1,698 in Aurora. An adapter that kept `signature` "for provenance"
would ship 6.9 MB of useless padding.

**Images are the largest and least predictable control.** RDI carried 89 base64
images inside `tool_result` parts — 13.7 MB, 68% of that session. The current
`strip_images()` walks `message.content` only, so every one of them would have
been uploaded. Aurora had 4.

**The two caps never fired on real data.** Zero writes exceeded 2000 lines; three
tool results exceeded 64 KB. They stay as bounded-cost guards against a
pathological session, and the spec does not claim savings for them. The
"2000-line truncation is lossless" property is therefore **asserted, not
demonstrated** — it aligns with `MAX_LINES_PER_EVENT`, the extractor's own hashing
cap, but no observed session exercised it.

Extraction equivalence *was* demonstrated for the controls that fired: attestation
output was identical with and without them across all five sessions tested
(RDI 75 items / 6,554 hashes unchanged; Aurora 82, 44 and 1 items unchanged).

### 9.3 Chunking

4 MB per chunk, one submission per session. The largest real session needs two
chunks. Each chunk carries `prefix_hash` — the hash of all preceding chunks — so
the server can reject reordered or altered sequences.

An interrupted upload is retried whole. At this size resumable multipart is not
justified; the state cursor makes a retry cheap.

---

## 10. Error handling

| Condition | Behaviour |
|---|---|
| No `config.json` for the cwd | Point at `cadra-connect`; do not guess a workspace |
| Token expired / invalid (401) | Report plainly; suggest re-connect with a fresh token |
| Session revoked (403) | Report the server's message; do not retry |
| Binding mismatch (409) | Report which remote the server expected; do not silently rebind |
| Network failure mid-chunk | Keep `state.json` unchanged; the session is retried whole next run |
| Transcript unreadable / malformed line | Skip the line, count it, report the count. Never abort a submission for one bad line |
| Nothing new to submit | Say so explicitly — silence reads as failure |

The plugin never reports success it has not been told about by the server.

---

## 11. Testing

No test infrastructure exists in this repo today; it is added with the rewrite.

- **Fixtures:** small synthetic transcript trees under `tests/fixtures/`, covering
  a main session, a subagent pair, absolute paths, tab-numbered reads, an embedded
  image, and a secret-bearing `.env` read.
- **Scoping:** sessions in/out by recorded `cwd`; subdirectory cwd included;
  sibling-prefix folder excluded; worktree cwd included.
- **Transformation:** each row of §7's table; path rebasing inside vs outside the
  workspace; subagent interleaving order and tagging.
- **Extraction parity — the load-bearing test:** feed the transformed envelope to
  the real `attestation_items_from_payload` from `cadra-prototype` and assert a
  non-zero, expected attestation count. This is what would have caught the
  absolute-path defect.
- **Redaction:** each rule class; assert `last-preview.json` is byte-identical to
  the submitted payload.
- **Filesystem invariant:** run a submission against a temp workspace and assert
  no write occurred outside `.cadra/` and `.gitignore`.
- **Chunking:** boundary and hash-chain correctness.

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Claude Code's transcript format is not a stable public contract, and already moved subagents out of the main file | `agent.version` and `capture_version` travel in every envelope; the server tolerates unknown keys; the extraction-parity test fails loudly on a format change |
| Client-side redaction is defeatable by editing the plugin | Proxy re-scans (D6); this is accepted as tamper-*evident*, not tamper-proof |
| A candidate can point `workspace_root` at unrelated work | Server-side binding check; and attestations only score against the submitted repo, so foreign material cannot inflate a score |
| A candidate never invokes `cadra-submit` | Open — see §13 |
| `tool-results/` offload directory may hold write content not present in the transcript | **Unresolved.** Must be checked before implementation; if write content is offloaded, those attestations are lost silently |

---

## 13. Open questions

1. **No-submission outcome.** With no hooks, a candidate who never runs
   `cadra-submit` submits nothing. Is that an accepted visible outcome, or is a
   reminder surface needed on the dashboard?
2. **`tool-results/` offload** (§12) — needs a targeted check.
3. **Multiple machines.** A candidate who works on two machines must connect on
   each; transcripts are local. Submissions merge server-side by `session_id`, but
   this is untested.

---

## 14. Sequencing

1. Config, filesystem contract, `cadra-connect` — establishes the ingest contract
   end to end against the companion spec's route.
2. Collection and scoping (§6), with the parity test from §11.
3. Transformation (§7).
4. Redaction (§8) and the preview surface.
5. Size controls and chunking (§9).
6. `cadra-submit` and `cadra-traces` wiring, error handling (§10).
7. Delete the superseded hooks, PowerShell scripts and Supabase code (§3).

Step 7 is last deliberately: the old path stays intact until the new one is
proven, so there is no window in which neither works.
