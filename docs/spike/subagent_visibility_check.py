"""Do subagent (Agent tool) file writes appear anywhere in the transcript?"""
import json, collections
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
sidechain = collections.Counter()
agent_calls = 0
per_project = {}

for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    sc = 0
    ac = 0
    sc_tools = collections.Counter()
    for f in d.glob("*.jsonl"):
        for line in open(f, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            is_sc = bool(e.get("isSidechain"))
            if is_sc:
                sc += 1
            msg = e.get("message")
            c = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(c, list):
                continue
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    if b.get("name") == "Agent":
                        ac += 1
                    if is_sc:
                        sc_tools[b.get("name")] += 1
    if ac or sc:
        per_project[d.name] = (ac, sc, dict(sc_tools))

print(f"{'project':46} {'Agent calls':>11} {'sidechain entries':>18}  sidechain tools")
for name, (ac, sc, tools) in sorted(per_project.items(), key=lambda kv: -kv[1][0]):
    print(f"{name[:46]:46} {ac:11} {sc:18}  {tools if tools else ''}")
