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
MAX_RESPONSE_BYTES = 1024 * 1024


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """urllib copies every header, Authorization included, into a redirect —
    cross-host. One 302 from a mistyped or hostile proxy would hand over the
    assessment token, so redirects are refused outright."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def _call(method: str, url: str, token: str, body: dict | None) -> tuple[int, dict]:
    if not url.startswith("https://"):
        return 0, {"error": {"code": "insecure_url",
                             "message": "the proxy address must be https://"}}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=TIMEOUT_S) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace") or "{}"
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


def bind_workspace(*, base_url: str, token: str, workspace_root: str) -> tuple[int, dict]:
    """Claim this folder for the assessment, and prove the token in one call.

    A write, so a POST on its own route rather than the read endpoint. Binding
    here rather than at first submission closes the trust-on-first-use window:
    connect happens on day zero, while the candidate is following the Setup
    instructions and demonstrably in the folder they just prepared. A first
    submission could be days later from anywhere.
    """
    return _call("POST", f"{base_url.rstrip('/')}/v1/traces/bind", token,
                 {"workspace_root": workspace_root})
