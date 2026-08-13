"""The token travels in a header, so where that header can end up is the risk."""
from cadra import client


def test_a_non_https_url_never_leaves_the_process():
    """No socket is opened at all — the check is before the request is built."""
    status, payload = client.post_chunk(base_url="http://proxy.test",
                                        token="tok", body={})
    assert status == 0
    assert payload["error"]["code"] == "insecure_url"


def test_redirects_are_refused_rather_than_followed():
    """urllib's default handler copies every header, Authorization included, into
    the redirected request — cross-host. One 302 would hand over the token."""
    handler = client._NoRedirects()
    assert handler.redirect_request(None, None, 302, "Found", {},
                                    "https://attacker.example/") is None
    assert client._NoRedirects in [type(h) for h in client._OPENER.handlers]


def test_the_token_appears_in_no_error_payload():
    status, payload = client.get_traces(base_url="https://127.0.0.1:1",
                                        token="s3cr3t-token-value")
    assert status == 0
    assert "s3cr3t" not in repr(payload)
