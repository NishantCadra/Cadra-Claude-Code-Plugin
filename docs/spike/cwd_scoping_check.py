"""Does a Claude Code transcript record its own cwd? If so, scoping can key on
the recorded cwd rather than the lossy encoded folder name."""
import json, collections
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
for name in ("C--Dev-cadra-dev", "C--Dev-cadra-dev-cadra-prototype", "C--Dev-RDI"):
    d = ROOT / name
    if not d.is_dir():
        continue
    cwds = collections.Counter()
    fields = collections.Counter()
    for f in list(d.glob("*.jsonl"))[:3]:
        for i, line in enumerate(open(f, encoding="utf-8", errors="ignore")):
            if i > 400:
                break
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            for k in ("cwd", "workspace", "projectPath", "gitBranch", "version"):
                if k in e:
                    fields[k] += 1
            if isinstance(e.get("cwd"), str):
                cwds[e["cwd"]] += 1
    print(f"{name}")
    print(f"   fields seen: {dict(fields)}")
    for c, n in cwds.most_common(4):
        print(f"   cwd={c}  ({n})")
