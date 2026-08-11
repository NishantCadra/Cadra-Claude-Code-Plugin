# G5 spike scripts

Investigation code kept for reproducibility of the numbers in
[`../cadra-integration-assessment.md`](../cadra-integration-assessment.md) §4.
Not production code and not part of the plugin runtime.

All three scripts read Claude Code's local session storage
(`~/.claude/projects/<encoded-cwd>/`) read-only. Nothing is uploaded.

## `g5_line_attestation_spike.py`

Adapts Claude Code JSONL into the OpenAI-style envelope that
`proxy/line_attest.py` expects, extracts attestations and read events, then runs
the real `integrity.build_integrity_summary()` against a repo's final on-disk
state. Produces the §4.1 results table.

```
cd <cadra-prototype>
backend\.venv\Scripts\python.exe <path>\g5_line_attestation_spike.py <transcript-dir> <repo-path>
```

`<transcript-dir>` is a folder name under `~/.claude/projects`, e.g. `C--Dev-RDI`.
It imports from a hardcoded `cadra-prototype` checkout path — edit `REPO_ROOT` if
yours differs.

Flags:

- `--raw` — disable the two adapter fixes (absolute-path rebasing and
  tab-prefixed line-number stripping), reproducing the naive-adapter row.
- `--no-subagents` — exclude `<session-id>/subagents/*.jsonl`, reproducing the
  middle row.

## `subagent_visibility_check.py`

Counts `Agent` tool calls against `isSidechain` entries across every local
project, establishing that subagent work never appears in the main transcript
(§4.4).

```
python subagent_visibility_check.py
```

## `size_control_measurement.py`

Produces the §9 measurements in
[`../specs/2026-08-11-byo-trace-capture-design.md`](../specs/2026-08-11-byo-trace-capture-design.md):
envelope size with each size control applied cumulatively, plus a check that
attestation output is identical with and without the controls.

```
cd <cadra-prototype>
backend\.venv\Scripts\python.exe <path>\size_control_measurement.py C--Dev-RDI C:\Dev\RDI
```

## `block_byte_breakdown.py`

Where the bytes actually are — per content-block type and per JSONL entry type.
This is what showed `tool_result` to be 79% of the payload and that "thinking"
cost is entirely the `signature` field, not reasoning text.

## `cwd_homogeneity_check.py`

Answers whether a transcript file has one `cwd` or several — the measurement
behind §6.1's origin-cwd rule. Result: 27 of 489 files carry more than one cwd
(some ten), because `cwd` tracks the agent's current directory as it moves during
a session. Also reports how often the first line already carries a `cwd` (91%),
which is what makes the one-line scoping probe in §6.1.1 cheap.

## `cwd_scoping_check.py`

Shows that transcripts record their own `cwd`, that one project folder can hold
several unrelated cwds, and that a subdirectory cwd lands in a separate folder —
the evidence behind the §6.1 scoping rule.

## `transcript_shape_inspector.py`

Dumps entry types, content-block types, tool names and tool-input key names from
a transcript directory — the raw material behind §4.2. Edit the `D` constant to
point at a different project.

```
python transcript_shape_inspector.py
```
