"""Claude Code -> canonical OpenAI-style envelope (§7)."""
from pathlib import Path

from cadra import adapt


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
