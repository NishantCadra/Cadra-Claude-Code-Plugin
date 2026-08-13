"""Inspect the real shape of Claude Code transcript entries before writing the adapter."""
import json, sys, collections
from pathlib import Path

D = Path.home() / ".claude" / "projects" / "C--Dev-loan-processing-harness"

types = collections.Counter()
block_types = collections.Counter()
tool_names = collections.Counter()
sidechain = collections.Counter()
sample_tool_use = {}
sample_tool_result = None

for f in sorted(D.glob("*.jsonl")):
    for line in open(f, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        types[e.get("type")] += 1
        sidechain[bool(e.get("isSidechain"))] += 1
        msg = e.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            block_types["<str>"] += 1
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            block_types[bt] += 1
            if bt == "tool_use":
                name = b.get("name")
                tool_names[name] += 1
                if name not in sample_tool_use:
                    sample_tool_use[name] = sorted((b.get("input") or {}).keys())
            if bt == "tool_result" and sample_tool_result is None:
                c = b.get("content")
                sample_tool_result = {
                    "keys": sorted(b.keys()),
                    "content_type": type(c).__name__,
                    "content_head": (c[:200] if isinstance(c, str)
                                     else json.dumps(c)[:200] if c is not None else None),
                }

print("entry types:      ", dict(types))
print("isSidechain:      ", dict(sidechain))
print("content blocks:   ", dict(block_types))
print("tool_use names:   ", dict(tool_names))
print("\ntool input keys by tool:")
for n, keys in sorted(sample_tool_use.items()):
    print(f"  {n:22} {keys}")
print("\nsample tool_result:", json.dumps(sample_tool_result, indent=2)[:600])
