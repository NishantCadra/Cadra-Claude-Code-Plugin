"""Spike: does Claude Code offload Write/Edit content into tool-results/?

Scans ~/.claude/projects for:
1. <persisted-output> stubs in tool_result bodies and which parent tool caused them
2. Write/Edit-family tool_use calls missing content/new_string in the JSONL

Verdict drives whether the BYO collector must read tool-results/ for attestation.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
PERSIST_RE = re.compile(r"<persisted-output>", re.I)
WRITE_TOOLS = {
    "write",
    "edit",
    "multiedit",
    "notebookedit",
    "create_file",
    "write_file",
}
# Keys that carry file body for attestation hashing.
WRITE_BODY_KEYS = ("content", "new_string", "old_string", "new_source", "patch", "input")


def main() -> None:
    tr_files = list(ROOT.rglob("tool-results/*.txt"))
    print(f"tool-results files on disk: {len(tr_files)}")

    offload_by_tool: Counter[str] = Counter()
    write_missing: list[dict] = []
    persist_samples: list[dict] = []
    sessions_with_offload: set[str] = set()
    sessions_checked = 0
    write_calls = 0
    write_with_content = 0
    persisted_results = 0

    for jsonl in ROOT.rglob("*.jsonl"):
        sessions_checked += 1
        tool_names: dict[str, str] = {}
        entries: list[dict] = []
        try:
            with jsonl.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    entries.append(obj)
                    msg = obj.get("message") or {}
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for part in content:
                        if not isinstance(part, dict) or part.get("type") != "tool_use":
                            continue
                        tid = str(part.get("id") or "")
                        name = str(part.get("name") or "")
                        if tid:
                            tool_names[tid] = name
                        if name.lower() not in WRITE_TOOLS:
                            continue
                        write_calls += 1
                        inp = part.get("input") or {}
                        has = False
                        if isinstance(inp, dict):
                            for k in WRITE_BODY_KEYS:
                                if isinstance(inp.get(k), str) and inp.get(k):
                                    has = True
                            for e in inp.get("edits") or []:
                                if isinstance(e, dict) and e.get("new_string"):
                                    has = True
                        if has:
                            write_with_content += 1
                        else:
                            write_missing.append(
                                {
                                    "file": str(jsonl.relative_to(ROOT)),
                                    "tool": name,
                                    "id": tid,
                                    "keys": list(inp.keys())
                                    if isinstance(inp, dict)
                                    else type(inp).__name__,
                                    "input_preview": str(inp)[:200],
                                }
                            )
        except OSError:
            continue

        for obj in entries:
            msg = obj.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "tool_result":
                    continue
                body = part.get("content")
                if not isinstance(body, str):
                    continue
                if not PERSIST_RE.search(body):
                    continue
                persisted_results += 1
                tid = str(part.get("tool_use_id") or "")
                tname = tool_names.get(tid, "?unknown")
                offload_by_tool[tname] += 1
                sessions_with_offload.add(str(jsonl.relative_to(ROOT)))
                if len(persist_samples) < 15:
                    persist_samples.append(
                        {
                            "session": str(jsonl.relative_to(ROOT)),
                            "tool": tname,
                            "tool_use_id": tid,
                            "snippet": body[:200].replace("\n", " "),
                        }
                    )

    print()
    print("=== SUMMARY ===")
    print(f"sessions/jsonl scanned: {sessions_checked}")
    print(f"Write/Edit-family tool_use calls: {write_calls}")
    print(f"  with content/new_string present: {write_with_content}")
    print(f"  missing write body: {len(write_missing)}")
    print(f"persisted tool_result stubs: {persisted_results}")
    print(f"sessions with offload: {len(sessions_with_offload)}")
    print()
    print("Offload by parent tool:")
    for k, v in offload_by_tool.most_common():
        print(f"  {k}: {v}")

    write_tool_names = {t.lower() for t in WRITE_TOOLS}
    write_offloads = sum(
        v for k, v in offload_by_tool.items() if k.lower() in write_tool_names
    )
    print()
    print(f"Offloads whose parent tool is Write/Edit-family: {write_offloads}")

    print()
    print("=== Persist samples ===")
    for s in persist_samples:
        print(f"{s['tool']} | {s['session']}")
        print(f"  {s['snippet']}")

    if write_missing:
        print()
        print("=== Write calls missing body (first 20) ===")
        for w in write_missing[:20]:
            print(w)

    print()
    if write_offloads == 0 and not write_missing:
        print(
            "VERDICT: tool-results/ holds oversized TOOL RESULTS only "
            "(Bash/Grep/etc). Write/Edit bodies remain in the JSONL. "
            "Collector need not read tool-results/ for attestation."
        )
    elif write_offloads or write_missing:
        print(
            "VERDICT: Write/Edit content may be missing from JSONL — "
            "collector MUST resolve tool-results/ (or equivalent) before attestation."
        )
    else:
        print("VERDICT: inconclusive — inspect samples above.")


if __name__ == "__main__":
    main()
