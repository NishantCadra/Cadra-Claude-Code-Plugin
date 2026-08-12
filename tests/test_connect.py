"""cadra-connect writes config and proves the token works (§5.1)."""
import json
from pathlib import Path

import pytest

import cadra_connect
from cadra import config


def _connect(workspace: Path, token: str):
    _paste(workspace, token)
    return cadra_connect.main(["--workspace", str(workspace),
                               "--proxy", "https://proxy.test"])


def _paste(workspace: Path, token: str) -> None:
    """What the candidate does by hand: put the token in the file. It never
    reaches a command line, so it never lands in a transcript."""
    cadra_connect.main(["--workspace", str(workspace), "--init"])
    cadra_connect.token_path(workspace).write_text(token, encoding="utf-8")


def _token(exp: int = 99999999999) -> str:
    import base64

    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return (f"{seg({'alg': 'HS256'})}."
            f"{seg({'coding_assessment_id': 'a-1', 'exp': exp})}.sig")


def test_connect_writes_config_and_gitignore(workspace: Path, monkeypatch):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    code = _connect(workspace, _token())
    assert code == 0
    cfg = config.load(workspace)
    assert cfg["token"] == _token()
    assert cfg["proxy_base_url"] == "https://proxy.test"
    assert ".cadra/" in (workspace / ".gitignore").read_text()


def test_connect_records_the_git_remote_when_present(workspace: Path, monkeypatch):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    monkeypatch.setattr(cadra_connect, "git_remote",
                        lambda ws: "https://github.com/c/s.git")
    _connect(workspace, _token())
    assert config.load(workspace)["git_remote"] == "https://github.com/c/s.git"


def test_expired_token_is_refused_before_anything_is_written(workspace: Path):
    code = _connect(workspace, _token(exp=1))
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_malformed_token_is_refused(workspace: Path):
    code = _connect(workspace, "nonsense")
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_server_rejection_does_not_leave_a_config(workspace: Path, monkeypatch):
    """Fail fast on day zero rather than at the deadline."""
    monkeypatch.setattr(cadra_connect, "verify_token",
                        lambda **kw: (False, "token not accepted (401)"))
    code = _connect(workspace, _token())
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_token_is_never_printed(workspace: Path, monkeypatch, capsys):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    _connect(workspace, _token())
    assert _token() not in capsys.readouterr().out


def test_token_never_needs_to_reach_a_command_line(workspace: Path, monkeypatch):
    """The whole point of the file: a token passed as an argument is recorded in
    the transcript by Claude Code, and cadra-submit uploads the transcript."""
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    assert _connect(workspace, _token()) == 0
    parser_args = cadra_connect.main.__doc__  # no --token option exists at all
    with pytest.raises(SystemExit):
        cadra_connect.main(["--workspace", str(workspace), "--token", _token()])
    assert parser_args is None


def test_paste_file_is_removed_once_the_token_is_stored(workspace: Path, monkeypatch):
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    _connect(workspace, _token())
    assert not cadra_connect.token_path(workspace).exists()
    assert config.load(workspace)["token"] == _token()


def test_init_ignores_cadra_before_the_token_can_be_pasted(workspace: Path):
    """Ordering matters: the folder must be ignored before it can hold a token."""
    cadra_connect.main(["--workspace", str(workspace), "--init"])
    assert ".cadra/" in (workspace / ".gitignore").read_text(encoding="utf-8")
    assert cadra_connect.token_path(workspace).parent.is_dir()
    assert not cadra_connect.token_path(workspace).exists()


def test_a_plain_http_proxy_is_refused(workspace: Path, monkeypatch):
    """urllib carries the Authorization header across a redirect, so an http://
    proxy hands the token to anyone on the path."""
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    _paste(workspace, _token())
    code = cadra_connect.main(["--workspace", str(workspace),
                               "--proxy", "http://proxy.test"])
    assert code == 1
    assert not config.config_path(workspace).exists()


def test_the_home_directory_is_refused_as_a_workspace(monkeypatch, tmp_path: Path):
    """Connecting at ~ would put every project folder beneath it in scope."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    code = cadra_connect.main(["--workspace", str(home), "--init"])
    assert code == 1
    assert not (home / ".cadra").exists()


def test_credentials_are_stripped_from_the_remote(workspace: Path, monkeypatch):
    """A repo cloned with an embedded PAT yields it verbatim from git, and the
    server's binding comparison discards credentials before comparing anyway."""
    from cadra import repo
    monkeypatch.setattr(cadra_connect, "verify_token", lambda **kw: (True, ""))
    monkeypatch.setattr(repo.subprocess, "run", lambda *a, **kw: type(
        "R", (), {"stdout": "https://u:ghp_liveTokenValue@github.com/o/r.git\n"})())
    _connect(workspace, _token())
    remote = config.load(workspace)["git_remote"]
    assert remote == "https://github.com/o/r.git"
    assert "ghp_" not in remote


def test_remote_forms_without_credentials_are_left_alone():
    for remote in ("https://github.com/o/r.git", "git@github.com:o/r.git",
                   "ssh://git@github.com/o/r.git", "/local/path/repo.git"):
        assert cadra_connect.strip_credentials(remote) == remote
    # A bare token as the username is the other form GitHub accepts.
    assert (cadra_connect.strip_credentials("https://ghp_tok@github.com/o/r.git")
            == "https://github.com/o/r.git")
