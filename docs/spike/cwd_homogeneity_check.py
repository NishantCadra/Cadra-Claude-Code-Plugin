"""Is a single transcript file cwd-homogeneous, or can one file hold several cwds?

Determines whether scoping can be decided per FILE (cheap, read one line) or must
be decided per ENTRY (expensive, and breaks tool_use/tool_result pairing on split).
"""
import json, collections
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
mixed = []
total_files = 0
first_line_has_cwd = 0

for d in sorted(ROOT.iterdir()):
    if not d.is_dir():
        continue
    files = list(d.glob("*.jsonl")) + list(d.glob("*/subagents/*.jsonl"))
    for f in files:
        cwds = collections.Counter()
        first_cwd_line = None
        for i, line in enumerate(open(f, encoding="utf-8", errors="ignore")):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = e.get("cwd")
            if isinstance(c, str) and c:
                cwds[c] += 1
                if first_cwd_line is None:
                    first_cwd_line = i
        if not cwds:
            continue
        total_files += 1
        if first_cwd_line == 0:
            first_line_has_cwd += 1
        if len(cwds) > 1:
            mixed.append((d.name, f.name, dict(cwds)))

print(f"files with a cwd: {total_files}")
print(f"  cwd present on the very first line: {first_line_has_cwd} "
      f"({100*first_line_has_cwd/max(total_files,1):.0f}%)")
print(f"  files containing MORE THAN ONE cwd: {len(mixed)}")
for dname, fname, c in mixed[:10]:
    print(f"    {dname}/{fname}")
    for k, v in c.items():
        print(f"        {v:5}x {k}")
