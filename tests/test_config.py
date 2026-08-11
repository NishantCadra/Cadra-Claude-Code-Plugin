"""Config lives in <workspace>/.cadra/ and the token never reaches git (§4)."""
import base64
import json
from pathlib import Path

import pytest

from cadra import config


def _token(claims: dict) -> str:
    def seg(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"{seg({'alg': 'HS256'})}.{seg(claims)}.signature"


def test_save_then_load_roundtrip(workspace: Path):
    config.save(workspace, {"token": "t", "workspace_root": str(workspace)})
    assert config.load(workspace)["token"] == "t"


def test_find_workspace_from_a_subdirectory(workspace: Path):
    config.save(workspace, {"token": "t"})
    nested = workspace / "src" / "deep"
    nested.mkdir(parents=True)
    assert config.find_workspace(nested) == workspace


def test_find_workspace_returns_none_when_unconfigured(tmp_path: Path):
    assert config.find_workspace(tmp_path) is None


def test_nested_workspace_resolves_to_the_innermost(workspace: Path):
    inner = workspace / "inner"
    inner.mkdir()
    config.save(workspace, {"token": "outer"})
    config.save(inner, {"token": "inner"})
    assert config.find_workspace(inner) == inner


def test_gitignore_is_created_with_the_entry(workspace: Path):
    assert config.ensure_gitignored(workspace) is True
    assert ".cadra/" in (workspace / ".gitignore").read_text()


def test_gitignore_append_is_idempotent(workspace: Path):
    (workspace / ".gitignore").write_text("node_modules/\n")
    config.ensure_gitignored(workspace)
    config.ensure_gitignored(workspace)
    text = (workspace / ".gitignore").read_text()
    assert text.count(".cadra/") == 1
    assert "node_modules/" in text  # existing entries preserved


def test_decode_claims_reads_the_payload_without_verifying():
    claims = config.decode_claims(_token({"coding_assessment_id": "a-1", "exp": 99}))
    assert claims["coding_assessment_id"] == "a-1"


def test_decode_claims_rejects_malformed_tokens():
    for bad in ("", "notatoken", "only.two"):
        with pytest.raises(ValueError):
            config.decode_claims(bad)
