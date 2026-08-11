"""G5 spike: can Cadra's F6 line-attestation math run on a Claude Code transcript?

Adapts Claude Code JSONL (Anthropic block format) into the OpenAI-style envelope
that proxy/line_attest.py expects, extracts attestations + read events, then runs
the REAL backend/services/integrity.py build_integrity_summary against the final
on-disk repo. Reports what agent_share / rollup a BYO candidate would receive.

Usage: g5_spike.py <transcript-dir-name> <repo-path>
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(r"C:\Dev\cadra-dev\cadra-prototype")
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from services import integrity  # noqa: E402
from services.line_attest import (  # noqa: E402
    attestation_items_from_payload,
    is_ignored_path,
    nontrivial_lines,
    normalize_path,
    read_items_from_payload,
)

TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".sql", ".yaml", ".yml",
    ".toml", ".css", ".html", ".sh", ".ps1", ".txt", ".env.example", ".cfg", ".ini",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist",
             "build", "out", ".mypy_cache", ".pytest_cache"}
MAX_FILE_BYTES = 400_000


# --------------------------------------------------------------- adapter
def load_entries(tdir: Path, *, with_subagents: bool = True) -> list[dict]:
    entries: list[dict] = []
    sources = sorted(tdir.glob("*.jsonl"))
    if with_subagents:
        subs = sorted(tdir.glob("*/subagents/*.jsonl"))
        print(f"  (+{len(subs)} subagent transcripts, "
              f"{sum(f.stat().st_size for f in subs) / 1e6:.1f} MB)")
        sources += subs
    for f in sources:
        for line in open(f, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


_PATH_ARG_KEYS = ("file_path", "filePath", "path", "target_file", "notebook_path")
_CC_LINENO_RE = __import__("re").compile(r"^\s*\d+\t")


def _rebase(value, repo: Path):
    """Claude Code emits ABSOLUTE tool paths (C:\\Dev\\x\\a.py). F6's _GLOBAL_PATH_RE
    discards drive-letter paths, so they must be rebased to workspace-relative."""
    if not isinstance(value, str):
        return value, False
    try:
        p = Path(value)
        if p.is_absolute():
            return str(p.relative_to(repo)).replace("\\", "/"), True
    except (ValueError, OSError):
        return value, False
    return value, False


def _strip_cc_linenos(content):
    """Claude Code Read results prefix lines with '<n>\\t'; F6's _strip_line_numbers
    only recognises |, : and -> separators, so tab-numbered reads never match."""
    if isinstance(content, list):
        return [
            {**b, "text": _strip_cc_linenos(b.get("text"))}
            if isinstance(b, dict) and isinstance(b.get("text"), str) else b
            for b in content
        ]
    if not isinstance(content, str):
        return content
    lines = content.split("\n")
    hits = sum(1 for line in lines if _CC_LINENO_RE.match(line))
    if not lines or hits / max(len(lines), 1) < 0.8:
        return content
    return "\n".join(_CC_LINENO_RE.sub("", line, count=1) for line in lines)


def adapt(entries: list[dict], repo: Path, *, fix: bool = True) -> tuple[dict, collections.Counter]:
    """Claude Code blocks -> OpenAI-style {"messages": [...]} for line_attest."""
    messages: list[dict] = []
    stats: collections.Counter = collections.Counter()
    for e in entries:
        msg = e.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        role = msg.get("role") or e.get("type")
        if not isinstance(content, list):
            continue
        if role == "assistant":
            tool_calls = []
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                stats[f"tool_use:{b.get('name')}"] += 1
                args = dict(b.get("input") or {})
                if fix:
                    for k in _PATH_ARG_KEYS:
                        if k in args:
                            args[k], did = _rebase(args[k], repo)
                            if did:
                                stats["rebased_path"] += 1
                tool_calls.append({
                    "id": b.get("id"),
                    "type": "function",
                    "function": {"name": b.get("name"), "arguments": args},
                })
            if tool_calls:
                messages.append({"role": "assistant", "tool_calls": tool_calls})
        elif role == "user":
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                stats["tool_result"] += 1
                content_out = b.get("content")
                if fix:
                    content_out = _strip_cc_linenos(content_out)
                messages.append({
                    "role": "tool",
                    "tool_call_id": b.get("tool_use_id"),
                    "content": content_out,
                })
    return {"messages": messages}, stats


# --------------------------------------------------------------- repo load
def load_repo_files(repo: Path) -> list[dict]:
    files = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files.append({"path": normalize_path(str(p.relative_to(repo))), "preview": text})
    return files


# --------------------------------------------------------------- main
def main() -> int:
    tdir = Path.home() / ".claude" / "projects" / sys.argv[1]
    repo = Path(sys.argv[2])
    fix = "--raw" not in sys.argv
    entries = load_entries(tdir, with_subagents="--no-subagents" not in sys.argv)
    payload, stats = adapt(entries, repo, fix=fix)

    print(f"=== {sys.argv[1]}  ->  {repo}   [adapter fixes: {'ON' if fix else 'OFF'}]")
    print(f"rebased abs paths  : {stats['rebased_path']}")
    print(f"transcript entries : {len(entries)}")
    print(f"adapted messages   : {len(payload['messages'])}")
    tool_stats = {k.split(':', 1)[1]: v for k, v in stats.items() if k.startswith('tool_use:')}
    print(f"tool_use calls     : {sum(tool_stats.values())}  {dict(sorted(tool_stats.items()))}")
    print(f"tool_results       : {stats['tool_result']}")

    items, shell_writes = attestation_items_from_payload(payload)
    reads = read_items_from_payload(payload)

    by_source: collections.Counter = collections.Counter()
    attestations: dict[str, set[str]] = {}
    for it in items:
        by_source[it["source"]] += 1
        attestations.setdefault(it["path"], set()).update(it["hashes"])
    truncated = {it["path"] for it in items if it.get("truncated")}

    print("\n--- extraction")
    print(f"attestation items  : {len(items)}  by source {dict(by_source)}")
    print(f"attested paths     : {len(attestations)}")
    print(f"attested hashes    : {sum(len(v) for v in attestations.values())}")
    print(f"shell_file_writes  : {shell_writes}")
    print(f"read events        : {len(reads)}  (paths {len({r['path'] for r in reads})})")
    print(f"truncated paths    : {len(truncated)}")

    repo_files = load_repo_files(repo)
    print(f"\n--- repo\nrepo files (text)  : {len(repo_files)}")

    summary = integrity.build_integrity_summary(
        repo_files=repo_files,
        attestations=attestations,
        truncated_paths=truncated,
        starter_files={},
        submitted_config_text=None,
        template_config_text=None,
        shell_file_writes=shell_writes,
        proxy_requests=[],
        paste_evidence=[],
        judge_unavailable=False,
        had_proxy_usage=True,      # BYO analogue: agent activity is monitored
        had_trace_activity=True,
        read_events=[
            {"kind": "read", "path": r["path"], "unattested_lines": 0} for r in reads
        ],
    )

    tot = summary["totals"]
    print("\n--- integrity summary (WHOLE repo)")
    print(f"lines {tot['lines']}  covered {tot['covered']}  agent_share {tot['agent_share']}")
    print(f"rollup: {summary['rollup']}")
    print("flags: " + ", ".join(k for k, v in summary["flags"].items() if v) or "flags: none")

    buckets = collections.Counter(f["bucket"] for f in summary["files"])
    print(f"buckets: {dict(buckets)}")

    # Restricted view: only files this transcript demonstrably wrote to.
    touched = {p for p in attestations}
    sub = [f for f in repo_files if f["path"] in touched]
    if sub:
        sub_summary = integrity.build_integrity_summary(
            repo_files=sub, attestations=attestations, truncated_paths=truncated,
            starter_files={}, submitted_config_text=None, template_config_text=None,
            shell_file_writes=shell_writes, proxy_requests=[], paste_evidence=[],
            judge_unavailable=False, had_proxy_usage=True, had_trace_activity=True,
        )
        st = sub_summary["totals"]
        print(f"\n--- restricted to the {len(sub)} attested files that still exist")
        print(f"lines {st['lines']}  covered {st['covered']}  agent_share {st['agent_share']}")
        print("buckets: " + str(dict(collections.Counter(
            f['bucket'] for f in sub_summary['files']))))
        worst = sorted(sub_summary["files"], key=lambda f: f["covered"] / max(f["lines"], 1))
        print("\nlowest-coverage attested files:")
        for f in worst[:8]:
            pct = 100 * f["covered"] / max(f["lines"], 1)
            print(f"  {pct:5.1f}%  {f['covered']:5}/{f['lines']:<5} {f['bucket']:18} {f['path'][:60]}")

    missing = sorted(touched - {f["path"] for f in repo_files})
    print(f"\nattested paths NOT found in repo: {len(missing)}")
    for p in missing[:8]:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
