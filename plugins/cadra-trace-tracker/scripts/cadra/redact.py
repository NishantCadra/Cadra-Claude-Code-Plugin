"""Secret redaction (spec §8). VENDORED COPY.

Canonical source is cadra-prototype/proxy/redact.py. Edit order on any rules
change: proxy -> backend -> plugin, then bump RULES_VERSION in all three.
Do not add rules here first.

Only the sentinel-delimited region below is shared; the release check hashes
exactly those bytes across the three copies (§8.0). `redact_messages` sits
outside it because it is plugin-only — the server has no use for the write
paths it returns.
"""
from __future__ import annotations

import math
import re
from typing import Any

# --- BEGIN SHARED REDACTION RULES (see byo-trace-capture-design §8.0) ---
RULES_VERSION = "1"

_TOKEN_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
]

_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)"
    r"[A-Z0-9_]*)(\s*[=:]\s*)(\S+)"
)

# Known-safe shapes that must never be redacted: redacting real code content
# breaks attestation line matching and penalises the candidate for our filter.
_SAFE_SHAPES = [
    re.compile(r"^[0-9a-f]{7,40}$"),                                   # git sha
    re.compile(r"^[0-9a-fA-F-]{36}$"),                                 # uuid
    re.compile(r"^[A-Za-z]:[\\/]"),                                    # windows path
]
_ENTROPY_CANDIDATE_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")
_ENTROPY_MIN_BITS = 4.0


def _shannon_bits(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _is_safe_shape(token: str) -> bool:
    return any(p.match(token) for p in _SAFE_SHAPES)


def redact_text(text: str) -> tuple[str, int]:
    """Returns (redacted, count). Never raises."""
    if not isinstance(text, str) or not text:
        return text, 0
    count = 0
    out = text
    for pattern in _TOKEN_PATTERNS:
        out, n = pattern.subn("[redacted:token]", out)
        count += n

    def _assign(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{match.group(2)}[redacted:secret]"

    out = _ASSIGNMENT_RE.sub(_assign, out)

    def _entropy(match: re.Match[str]) -> str:
        nonlocal count
        token = match.group(0)
        if _is_safe_shape(token) or _shannon_bits(token) < _ENTROPY_MIN_BITS:
            return token
        count += 1
        return "[redacted:entropy]"

    out = _ENTROPY_CANDIDATE_RE.sub(_entropy, out)
    return out, count
# --- END SHARED REDACTION RULES ---


WRITE_CONTENT_KEYS = ("content", "new_string", "file_text", "code_edit", "newString")
PATH_ARG_KEYS = ("file_path", "filePath", "path", "target_file", "notebook_path")


def redact_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str], int]:
    """Redact in place. Returns (messages, redacted_write_paths, count).

    Write-argument redaction changes the very lines attestation matches against the
    repo, so those paths are reported and later marked truncated — the file leaves
    the coverage denominator instead of scoring as unattested (§8.1).
    """
    total = 0
    redacted_paths: set[str] = set()
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"], n = redact_text(content)
            total += n
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            args = (call.get("function") or {}).get("arguments")
            if not isinstance(args, dict):
                continue
            path = next((args[k] for k in PATH_ARG_KEYS
                         if isinstance(args.get(k), str)), None)
            touched = 0
            for key in WRITE_CONTENT_KEYS:
                if isinstance(args.get(key), str):
                    args[key], n = redact_text(args[key])
                    touched += n
            for edit in args.get("edits") or []:
                if isinstance(edit, dict):
                    for key in WRITE_CONTENT_KEYS:
                        if isinstance(edit.get(key), str):
                            edit[key], n = redact_text(edit[key])
                            touched += n
            if touched and isinstance(path, str):
                redacted_paths.add(path)
            total += touched
    return messages, redacted_paths, total
