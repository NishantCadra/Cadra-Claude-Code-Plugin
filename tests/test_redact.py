"""Client-side redaction (§8). Vendored copy of the canonical proxy module."""
from cadra.redact import RULES_VERSION, redact_messages, redact_text


def test_rules_version_is_declared():
    assert RULES_VERSION == "1"


def test_tokens_are_redacted():
    for secret in ("sk-abcdefghijklmnopqrstuvwxyz012345",
                   "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                   "AKIAIOSFODNN7EXAMPLE"):
        out, n = redact_text(f"value {secret} end")
        assert secret not in out and n == 1


def test_assignment_keeps_key_drops_value():
    out, n = redact_text("DATABASE_PASSWORD=hunter2supersecret")
    assert out.startswith("DATABASE_PASSWORD=") and "hunter2" not in out and n == 1


def test_git_sha_and_uuid_survive():
    """False positives here would damage attestation coverage."""
    for safe in ("9ee8167a1b2c3d4e5f60718293a4b5c6d7e8f900",
                 "62cda7a2-399b-462b-8b92-11472cd32750"):
        out, n = redact_text(f"id {safe}")
        assert safe in out and n == 0


def test_tool_result_bodies_are_redacted():
    messages = [{"role": "tool", "tool_call_id": "t1",
                 "content": "AWS_SECRET=abcdef123456789"}]
    out, paths, n = redact_messages(messages)
    assert n == 1 and paths == set()
    assert "abcdef123456789" not in out[0]["content"]


def test_redacted_write_content_reports_its_path():
    """Redacting a write changes the lines attestation hashes, so the file must be
    excluded from coverage rather than scored as unattested (§8.1)."""
    messages = [{"role": "assistant", "tool_calls": [{
        "id": "t1", "type": "function", "function": {
            "name": "Write", "arguments": {
                "file_path": "src/config.py",
                "content": "API_KEY=sk-abcdefghijklmnopqrstuvwxyz012345\n"}}}]}]
    out, paths, n = redact_messages(messages)
    assert n >= 1
    assert paths == {"src/config.py"}
    assert "sk-abcdefghij" not in str(out)


def test_clean_write_content_reports_no_path():
    messages = [{"role": "assistant", "tool_calls": [{
        "id": "t1", "type": "function", "function": {
            "name": "Write", "arguments": {"file_path": "src/a.py",
                                           "content": "x = 1\n"}}}]}]
    _out, paths, n = redact_messages(messages)
    assert paths == set() and n == 0


def test_shared_region_sentinels_are_present_and_well_formed():
    """§8.0's cross-repo drift check hashes the bytes between these markers.
    Without them the check has nothing to hash and would silently pass."""
    from pathlib import Path

    from cadra import redact as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    begin = "# --- BEGIN SHARED REDACTION RULES"
    end = "# --- END SHARED REDACTION RULES ---"
    assert source.count(begin) == 1 and source.count(end) == 1
    shared = source[source.index(begin):source.index(end)]
    assert "def redact_text" in shared, "the rule engine must be inside the region"
    assert "def redact_messages" not in shared, "plugin-only code must be outside"
