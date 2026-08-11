"""Measure the plugin's size-control policy against real Claude Code transcripts.

For each session (main transcript + its subagent transcripts) builds the canonical
OpenAI-style envelope with size controls applied cumulatively, and reports the
payload bytes at each stage. Then verifies the claim that truncating write content
at MAX_LINES_PER_EVENT loses ZERO attestation signal.

Usage: size_measure.py <transcript-dir-name> [workspace-root]
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(r"C:\Dev\cadra-dev\cadra-prototype")
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from services.line_attest import (  # noqa: E402
    MAX_LINES_PER_EVENT,
    attestation_items_from_payload,
    nontrivial_lines,
)

PATH_ARG_KEYS = ("file_path", "filePath", "path", "target_file", "notebook_path")
WRITE_CONTENT_KEYS = ("content", "new_string", "file_text", "code_edit", "newString")
CC_LINENO_RE = re.compile(r"^\s*\d+\t")
TOOL_RESULT_CAP = 64 * 1024
CHUNK_BYTES = 4 * 1024 * 1024

STAGES = ("raw", "image_placeholder", "drop_thinking", "cap_tool_results", "cap_write_lines")


def load_session_groups(tdir: Path) -> dict[str, list[Path]]:
    """session_id -> [main jsonl, *subagent jsonls]."""
    groups: dict[str, list[Path]] = collections.defaultdict(list)
    for f in sorted(tdir.glob("*.jsonl")):
        groups[f.stem].append(f)
    for f in sorted(tdir.glob("*/subagents/*.jsonl")):
        groups[f.parent.parent.name].append(f)
    return groups


def read_entries(files: list[Path]) -> list[dict]:
    out = []
    for f in files:
        is_sub = f.parent.name == "subagents"
        for line in open(f, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict):
                e["__sub"] = is_sub
                out.append(e)
    out.sort(key=lambda e: str(e.get("timestamp") or ""))
    return out


def strip_linenos(text: str) -> str:
    lines = text.split("\n")
    hits = sum(1 for line in lines if CC_LINENO_RE.match(line))
    if hits / max(len(lines), 1) < 0.8:
        return text
    return "\n".join(CC_LINENO_RE.sub("", line, count=1) for line in lines)


def truncate_lines(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.split("\n")
    if len(nontrivial_lines(text)) <= max_lines:
        return text, False
    kept, n = [], 0
    for line in lines:
        kept.append(line)
        if sum(1 for c in line if not c.isspace()) >= 4:
            n += 1
            if n >= max_lines:
                break
    return "\n".join(kept) + "\n[truncated by cadra capture]", True


def build(entries: list[dict], workspace: Path | None, stage: str) -> tuple[list[dict], dict]:
    """Build the OpenAI-style message list with controls up to `stage` applied."""
    upto = STAGES.index(stage)
    drop_thinking = upto >= STAGES.index("drop_thinking")
    img = upto >= STAGES.index("image_placeholder")
    cap_tr = upto >= STAGES.index("cap_tool_results")
    cap_wr = upto >= STAGES.index("cap_write_lines")

    messages: list[dict] = []
    stats = collections.Counter()
    truncated_paths: set[str] = set()

    for e in entries:
        msg = e.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        role = msg.get("role") or e.get("type")
        if isinstance(content, str):
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        if role == "assistant":
            tool_calls, texts = [], []
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "thinking":
                    if drop_thinking:
                        stats["thinking_dropped"] += 1
                        continue
                    texts.append(str(b.get("thinking") or ""))
                elif bt == "text":
                    texts.append(str(b.get("text") or ""))
                elif bt == "tool_use":
                    args = dict(b.get("input") or {})
                    if workspace is not None:
                        for k in PATH_ARG_KEYS:
                            v = args.get(k)
                            if isinstance(v, str):
                                try:
                                    p = Path(v)
                                    if p.is_absolute():
                                        args[k] = str(p.relative_to(workspace)).replace("\\", "/")
                                except (ValueError, OSError):
                                    pass
                    if cap_wr:
                        for k in WRITE_CONTENT_KEYS:
                            v = args.get(k)
                            if isinstance(v, str):
                                new, did = truncate_lines(v, MAX_LINES_PER_EVENT)
                                if did:
                                    args[k] = new
                                    stats["writes_truncated"] += 1
                                    pv = args.get("file_path") or args.get("path")
                                    if isinstance(pv, str):
                                        truncated_paths.add(pv)
                        for sub in args.get("edits") or []:
                            if isinstance(sub, dict):
                                for k in WRITE_CONTENT_KEYS:
                                    v = sub.get(k)
                                    if isinstance(v, str):
                                        new, did = truncate_lines(v, MAX_LINES_PER_EVENT)
                                        if did:
                                            sub[k] = new
                                            stats["writes_truncated"] += 1
                    entry = {"id": b.get("id"), "type": "function",
                             "function": {"name": b.get("name"), "arguments": args}}
                    if e.get("__sub"):
                        entry["cadra_agent"] = {"agent_type": "subagent"}
                    tool_calls.append(entry)
            out: dict = {"role": "assistant"}
            if texts:
                out["content"] = "\n".join(texts)
            if tool_calls:
                out["tool_calls"] = tool_calls
            if len(out) > 1:
                messages.append(out)

        elif role == "user":
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "image":
                    if img:
                        stats["images_stripped"] += 1
                    else:
                        messages.append({"role": "user",
                                         "content": json.dumps(b.get("source") or b)})
                    continue
                if b.get("type") != "tool_result":
                    if b.get("type") == "text":
                        messages.append({"role": "user", "content": str(b.get("text") or "")})
                    continue
                c = b.get("content")
                if isinstance(c, list):
                    parts = []
                    for p in c:
                        if isinstance(p, dict):
                            if p.get("type") == "image":
                                if img:
                                    stats["images_stripped"] += 1
                                    parts.append("[image removed before upload]")
                                else:
                                    # what a naive adapter would actually ship
                                    parts.append(json.dumps(p.get("source") or p))
                                    stats["image_bytes"] += len(
                                        json.dumps(p.get("source") or p))
                                continue
                            parts.append(str(p.get("text") or ""))
                    c = "\n".join(parts)
                if not isinstance(c, str):
                    continue
                c = strip_linenos(c)
                if cap_tr and len(c.encode("utf-8")) > TOOL_RESULT_CAP:
                    half = TOOL_RESULT_CAP // 2
                    c = c[:half] + "\n[truncated by cadra capture]\n" + c[-half:]
                    stats["tool_results_capped"] += 1
                messages.append({"role": "tool", "tool_call_id": b.get("tool_use_id"),
                                 "content": c})
    stats["truncated_paths"] = len(truncated_paths)
    return messages, stats


def size_of(messages: list[dict]) -> int:
    return len(json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8"))


def attest_signal(messages: list[dict]) -> tuple[int, int]:
    items, _ = attestation_items_from_payload({"messages": messages})
    return len(items), sum(len(i["hashes"]) for i in items)


def main() -> int:
    tdir = Path.home() / ".claude" / "projects" / sys.argv[1]
    workspace = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    groups = load_session_groups(tdir)

    print(f"=== {sys.argv[1]}   workspace={workspace}")
    print(f"{'session':12} {'raw MB':>8} {'-img':>8} {'-think':>8} {'-tr64k':>8} "
          f"{'-wr2k':>8} {'saved':>7} {'chunks':>7}")

    grand = collections.Counter()
    for sid, files in sorted(groups.items(), key=lambda kv: -sum(f.stat().st_size for f in kv[1])):
        on_disk = sum(f.stat().st_size for f in files)
        if on_disk < 200_000:
            continue
        entries = read_entries(files)
        sizes, laststats = {}, None
        for stage in STAGES:
            msgs, st = build(entries, workspace, stage)
            sizes[stage] = size_of(msgs)
            laststats = st
        final = sizes["cap_write_lines"]
        saved = 100 * (1 - final / sizes["raw"]) if sizes["raw"] else 0
        chunks = max(1, -(-final // CHUNK_BYTES))
        print(f"{sid[:12]:12} {sizes['raw']/1e6:8.2f} {sizes['image_placeholder']/1e6:8.2f} "
              f"{sizes['drop_thinking']/1e6:8.2f} {sizes['cap_tool_results']/1e6:8.2f} "
              f"{final/1e6:8.2f} {saved:6.1f}% {chunks:7}")
        grand["on_disk"] += on_disk
        grand["raw"] += sizes["raw"]
        grand["final"] += final
        for k, v in (laststats or {}).items():
            grand[k] += v

    print(f"\non-disk total {grand['on_disk']/1e6:.1f} MB → envelope raw "
          f"{grand['raw']/1e6:.2f} MB → controlled {grand['final']/1e6:.2f} MB "
          f"({100*(1-grand['final']/max(grand['raw'],1)):.1f}% saved)")
    print(f"thinking dropped {grand['thinking_dropped']}, images {grand['images_stripped']}, "
          f"tool_results capped {grand['tool_results_capped']}, "
          f"writes truncated {grand['writes_truncated']}")

    # --- the load-bearing claim: 2000-line truncation costs no attestation signal
    print("\n--- attestation signal, uncontrolled vs controlled")
    for sid, files in sorted(groups.items(), key=lambda kv: -sum(f.stat().st_size for f in kv[1]))[:3]:
        entries = read_entries(files)
        raw_msgs, _ = build(entries, workspace, "raw")
        ctl_msgs, _ = build(entries, workspace, "cap_write_lines")
        a1, h1 = attest_signal(raw_msgs)
        a2, h2 = attest_signal(ctl_msgs)
        verdict = "IDENTICAL" if (a1, h1) == (a2, h2) else f"LOST {h1-h2} hashes"
        print(f"  {sid[:12]:12} items {a1}->{a2}  hashes {h1}->{h2}   {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
