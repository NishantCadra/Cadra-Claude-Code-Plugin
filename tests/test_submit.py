"""End-to-end submission against a stubbed proxy (§5.2, §10).

No test in this file may make a real network call: `client.post_chunk` is always
replaced. The proxy does not exist yet.
"""
import json
from pathlib import Path

import pytest

import cadra_submit
from cadra import config
from tests.conftest import write_jsonl


@pytest.fixture
def connected(workspace: Path, transcripts: Path):
    config.save(workspace, {"token": "tok", "workspace_root": str(workspace),
                            "proxy_base_url": "https://proxy.test",
                            "git_remote": "https://github.com/c/s.git"})
    from cadra import collect
    enc = collect.encode_dir_name(Path(str(workspace)).resolve())
    write_jsonl(transcripts / enc / "sess1.jsonl", [
        {"type": "user", "cwd": str(workspace), "sessionId": "sess1",
         "timestamp": "2026-08-11T09:00:00Z", "version": "2.0.14",
         "message": {"role": "user", "content": "build it"}},
        {"type": "assistant", "cwd": str(workspace), "timestamp": "2026-08-11T09:00:05Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Write",
              "input": {"file_path": str(workspace / "a.py"), "content": "x = 1\n"}}]}},
    ])
    return workspace


def test_submission_posts_the_expected_envelope(connected: Path, transcripts: Path,
                                                monkeypatch):
    sent: list[dict] = []

    def _post(*, base_url, token, body):
        sent.append(body)
        return 202, {"accepted": True, "session_id": body["session_id"],
                     "messages": len(body["messages"]), "received_at": "now"}

    monkeypatch.setattr(cadra_submit.client, "post_chunk", _post)
    code = cadra_submit.main(["--workspace", str(connected),
                              "--projects-root", str(transcripts)])
    assert code == 0
    body = sent[0]
    assert body["session_id"] == "sess1"
    assert "assessment_id" not in body          # identity comes from the token
    assert body["binding"]["git_remote"] == "https://github.com/c/s.git"
    assert body["agent"]["name"] == "claude-code"
    assert body["agent"]["version"] == "2.0.14"
    assert body["messages"][0]["client_ts"] == "2026-08-11T09:00:00Z"
    args = body["messages"][1]["tool_calls"][0]["function"]["arguments"]
    assert args["file_path"] == "a.py"          # rebased


def test_nothing_new_is_reported_explicitly(connected: Path, transcripts: Path,
                                            monkeypatch, capsys):
    monkeypatch.setattr(cadra_submit.client, "post_chunk",
                        lambda **kw: (202, {"accepted": True, "session_id": "sess1",
                                            "messages": 2, "received_at": "now"}))
    cadra_submit.main(["--workspace", str(connected), "--projects-root", str(transcripts)])
    capsys.readouterr()
    cadra_submit.main(["--workspace", str(connected), "--projects-root", str(transcripts)])
    assert "already submitted" in capsys.readouterr().out.lower()


def test_server_rejection_is_reported_and_state_not_advanced(
    connected: Path, transcripts: Path, monkeypatch, capsys
):
    monkeypatch.setattr(cadra_submit.client, "post_chunk",
                        lambda **kw: (403, {"error": {"code": "rejected_revoked",
                                                      "message": "disconnected"}}))
    code = cadra_submit.main(["--workspace", str(connected),
                              "--projects-root", str(transcripts)])
    assert code == 1
    assert "rejected_revoked" in capsys.readouterr().out
    state = json.loads((connected / ".cadra" / "state.json").read_text()) \
        if (connected / ".cadra" / "state.json").exists() else {}
    assert "sess1" not in state


def test_preview_is_written_and_matches_what_was_sent(connected: Path,
                                                      transcripts: Path, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(cadra_submit.client, "post_chunk",
                        lambda **kw: (sent.append(kw["body"]),
                                      (202, {"accepted": True, "session_id": "sess1",
                                             "messages": 2, "received_at": "n"}))[1])
    cadra_submit.main(["--workspace", str(connected), "--projects-root", str(transcripts)])
    preview = json.loads((connected / ".cadra" / "last-preview.json").read_text())
    assert preview["sessions"][0]["messages"] == sent[0]["messages"]


def test_unconnected_workspace_points_at_connect(workspace: Path, transcripts: Path,
                                                 capsys):
    code = cadra_submit.main(["--workspace", str(workspace),
                              "--projects-root", str(transcripts)])
    assert code == 1
    assert "cadra-connect" in capsys.readouterr().out
