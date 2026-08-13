"""What keys do thinking / text / tool_result blocks actually carry, and how big are they?"""
import json, collections
from pathlib import Path

D = Path.home() / ".claude" / "projects" / "C--Dev-RDI"
keys = collections.defaultdict(collections.Counter)
bytes_by_type = collections.Counter()
count_by_type = collections.Counter()
entry_bytes = collections.Counter()

files = list(D.glob("*.jsonl")) + list(D.glob("*/subagents/*.jsonl"))
for f in files:
    for line in open(f, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry_bytes[e.get("type")] += len(line)
        msg = e.get("message")
        c = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            for k in b:
                keys[t][k] += 1
            bytes_by_type[t] += len(json.dumps(b))
            count_by_type[t] += 1

print("block keys:")
for t, kc in keys.items():
    print(f"  {t:14} {dict(kc)}")
print("\nblock bytes (MB) / count:")
for t, n in bytes_by_type.most_common():
    print(f"  {t:14} {n/1e6:8.2f} MB  x{count_by_type[t]}")
print("\nJSONL bytes by entry type (MB):")
for t, n in entry_bytes.most_common(10):
    print(f"  {str(t):24} {n/1e6:8.2f}")
