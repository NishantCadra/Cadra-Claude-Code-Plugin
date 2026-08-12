"""Claude Code -> canonical OpenAI-style envelope (§7)."""
import json
from pathlib import Path

from cadra import adapt
from tests.conftest import write_jsonl


def _assistant(blocks, ts="2026-08-11T09:00:00Z", **over):
    entry = {"type": "assistant", "timestamp": ts, "cwd": "C:/Dev/ws",
             "message": {"role": "assistant", "content": blocks}}
    entry.update(over)
    return entry


def _tool_result(tid, content, ts="2026-08-11T09:00:01Z"):
    return {"type": "user", "timestamp": ts, "cwd": "C:/Dev/ws",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": content}]}}


WS = Path("C:/Dev/ws")


def test_tool_use_becomes_a_tool_call():
    out = adapt.to_messages([_assistant([
        {"type": "tool_use", "id": "t1", "name": "Write",
         "input": {"file_path": "C:/Dev/ws/src/a.py", "content": "x = 1\n"}}])], WS)
    call = out[0]["tool_calls"][0]
    assert call["id"] == "t1"
    assert call["function"]["name"] == "Write"
    assert call["function"]["arguments"]["file_path"] == "src/a.py"


def test_paths_outside_the_workspace_stay_absolute():
    """So the server's _GLOBAL_PATH_RE discards them and they are never attested."""
    out = adapt.to_messages([_assistant([
        {"type": "tool_use", "id": "t1", "name": "Write",
         "input": {"file_path": "C:/Other/secret.py", "content": "x = 1\n"}}])], WS)
    assert out[0]["tool_calls"][0]["function"]["arguments"]["file_path"] == \
        "C:/Other/secret.py"


def test_tab_numbered_read_results_are_stripped():
    out = adapt.to_messages([_tool_result("t1", "     1\timport os\n     2\tx = 1")], WS)
    assert out[0]["content"] == "import os\nx = 1"


def test_prose_that_merely_starts_with_a_number_is_not_stripped():
    out = adapt.to_messages([_tool_result("t1", "1\tfirst\nplain line\nanother line")], WS)
    assert "1\tfirst" in out[0]["content"]


def test_thinking_blocks_are_dropped_including_signature():
    out = adapt.to_messages([_assistant([
        {"type": "thinking", "thinking": "", "signature": "A" * 2000},
        {"type": "text", "text": "done"}])], WS)
    assert "A" * 100 not in str(out)
    assert out[0]["content"] == "done"


def test_images_become_placeholders_inside_tool_results():
    out = adapt.to_messages([_tool_result("t1", [
        {"type": "image", "source": {"data": "B" * 5000}},
        {"type": "text", "text": "ok"}])], WS)
    assert "B" * 100 not in str(out)
    assert "[image removed before upload]" in out[0]["content"]


def test_every_message_carries_client_ts():
    """Without this the server's velocity clock flags the candidate (§7.3)."""
    out = adapt.to_messages([_assistant([{"type": "text", "text": "hi"}],
                                        ts="2026-08-11T10:11:12Z")], WS)
    assert out[0]["client_ts"] == "2026-08-11T10:11:12Z"


def test_entry_without_a_timestamp_omits_client_ts_rather_than_guessing():
    entry = _assistant([{"type": "text", "text": "hi"}])
    del entry["timestamp"]
    out = adapt.to_messages([entry], WS)
    assert "client_ts" not in out[0]


def test_non_conversation_entry_types_are_dropped():
    entries = [{"type": t, "cwd": "C:/Dev/ws"} for t in
               ("mode", "permission-mode", "ai-title", "file-history-snapshot",
                "attachment", "queue-operation", "agent-name", "last-prompt")]
    assert adapt.to_messages(entries, WS) == []


def _sub_session(transcripts: Path, workspace: Path, meta: dict | None):
    """A one-session tree with a single subagent, optionally with a sidecar."""
    from cadra import collect
    enc = collect.encode_dir_name(workspace)
    base = {"cwd": str(workspace), "sessionId": "s1",
            "timestamp": "2026-08-11T09:00:00Z"}
    write_jsonl(transcripts / enc / "s1.jsonl",
                [{**base, "type": "user",
                  "message": {"role": "user", "content": "main"}}])
    write_jsonl(transcripts / enc / "s1" / "subagents" / "agent-a1.jsonl",
                [{**base, "type": "assistant", "timestamp": "2026-08-11T09:00:01Z",
                  "message": {"role": "assistant",
                              "content": [{"type": "text", "text": "sub"}]}}])
    if meta is not None:
        sidecar = transcripts / enc / "s1" / "subagents" / "agent-a1.meta.json"
        sidecar.write_text(json.dumps(meta), encoding="utf-8")
    sessions, _notes = collect.discover(transcripts, workspace)
    return sessions[0]


def test_subagent_messages_carry_the_real_agent_type_and_parent_call(
    transcripts: Path, workspace: Path
):
    """The sidecar has both fields; emitting a literal 'subagent' would throw
    away which agent actually did the work (§7)."""
    session = _sub_session(transcripts, workspace,
                           {"agentType": "code-reviewer",
                            "toolUseId": "toolu_01Kai", "description": "review"})
    messages, _meta = adapt.load_session(session, workspace)
    main = [m for m in messages if "cadra_agent" not in m]
    sub = [m for m in messages if "cadra_agent" in m]
    assert [m["content"] for m in main] == ["main"]
    assert sub[0]["cadra_agent"] == {"parent_tool_use_id": "toolu_01Kai",
                                     "agent_type": "code-reviewer"}


def test_missing_sidecar_still_tags_the_message_without_inventing_a_parent(
    transcripts: Path, workspace: Path
):
    session = _sub_session(transcripts, workspace, None)
    messages, _meta = adapt.load_session(session, workspace)
    sub = [m for m in messages if "cadra_agent" in m]
    assert sub[0]["cadra_agent"] == {"agent_type": "subagent"}


def test_main_transcript_messages_are_never_tagged(
    transcripts: Path, workspace: Path
):
    session = _sub_session(transcripts, workspace, {"agentType": "general-purpose"})
    messages, _meta = adapt.load_session(session, workspace)
    assert "cadra_agent" not in messages[0]


def test_dot_segments_are_collapsed_before_rebasing():
    """`src/../a.py` reaching the server unresolved matches no repo file, so the
    write silently scores as unattested."""
    assert adapt.rebase_path("C:/Dev/ws/src/../a.py", WS) == "a.py"
    assert adapt.rebase_path("C:/Dev/ws/./src/a.py", WS) == "src/a.py"
