"""cadra-connect writes config and proves the token works (§5.1)."""
import json
from pathlib import Path

import pytest

import cadra_connect
from cadra import config


def _token(exp: int = 99999999999) -> str:
    import base64

    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return (f"{seg({'alg': 'HS256'})}."
            f"{seg({'coding_assessment_id': 'a-1', 'exp': exp})}.sig")


def test_connect_writes_config_and_gitignore(workspace: Path, monkeypatch):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    code = cadra_connect.main(["--token", _token(), "--workspace", str(workspace),
                               "--proxy", "https://proxy.test"])
    assert code == 0
    cfg = config.load(workspace)
    assert cfg["token"] == _token()
    assert cfg["proxy_base_url"] == "https://proxy.test"
    assert ".cadra/" in (workspace / ".gitignore").read_text()


def test_connect_records_the_git_remote_when_present(workspace: Path, monkeypatch):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    monkeypatch.setattr(cadra_connect, "git_remote",
                        lambda ws: "https://github.com/c/s.git")
    cadra_connect.main(["--token", _token(), "--workspace", str(workspace),
                        "--proxy", "https://proxy.test"])
    assert config.load(workspace)["git_remote"] == "https://github.com/c/s.git"


def test_expired_token_is_refused_before_anything_is_written(workspace: Path):
    code = cadra_connect.main(["--token", _token(exp=1), "--workspace", str(workspace),
                               "--proxy", "https://proxy.test"])
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_malformed_token_is_refused(workspace: Path):
    code = cadra_connect.main(["--token", "nonsense", "--workspace", str(workspace),
                               "--proxy", "https://proxy.test"])
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_server_rejection_does_not_leave_a_config(workspace: Path, monkeypatch):
    """Fail fast on day zero rather than at the deadline."""
    monkeypatch.setattr(cadra_connect, "verify_token",
                        lambda **kw: (False, "token not accepted (401)"))
    code = cadra_connect.main(["--token", _token(), "--workspace", str(workspace),
                               "--proxy", "https://proxy.test"])
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_token_is_never_printed(workspace: Path, monkeypatch, capsys):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    cadra_connect.main(["--token", _token(), "--workspace", str(workspace),
                        "--proxy", "https://proxy.test"])
    assert _token() not in capsys.readouterr().out
