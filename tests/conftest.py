"""Shared fixtures. Every test uses a temp workspace — never the real home dir."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "solution"
    ws.mkdir()
    return ws


@pytest.fixture
def transcripts(tmp_path: Path) -> Path:
    """Stands in for ~/.claude/projects."""
    root = tmp_path / "projects"
    root.mkdir()
    return root


def write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
