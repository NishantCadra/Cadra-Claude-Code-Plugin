"""HTTP client for the Cadra proxy. Standard library only (spec §5.2, §10).

Every failure is turned into a (status, payload) pair rather than an exception, so
the caller can report it and leave `state.json` untouched. Status 0 means the
request never reached the server. The token appears only in the Authorization
header — never in a message, a log line or an exception string.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT_S = 120


def _call(method: str, url: str, token: str, body: dict | None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read().decode("utf-8") or "{}")
        except Exception:
            return err.code, {"error": {"code": f"http_{err.code}",
                                        "message": "request failed"}}
    except Exception as exc:
        # Only the exception type — an exception's text can carry the URL, and a
        # future signed URL would carry credentials.
        return 0, {"error": {"code": "network_error", "message": type(exc).__name__}}


def post_chunk(*, base_url: str, token: str, body: dict) -> tuple[int, dict]:
    return _call("POST", f"{base_url.rstrip('/')}/v1/traces", token, body)


def get_traces(*, base_url: str, token: str) -> tuple[int, dict]:
    return _call("GET", f"{base_url.rstrip('/')}/v1/traces", token, None)
