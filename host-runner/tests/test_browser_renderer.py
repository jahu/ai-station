import base64
import io

import pytest
from ai_station_runner import browser_renderer as renderer


def reply(**overrides):
    return {
        "id": 1,
        "status": 200,
        "headers": {"content-type": "text/html"},
        "body": base64.b64encode(b"public page").decode(),
        **overrides,
    }


def test_response_decoding_allows_bounded_public_content():
    assert renderer.response_body(reply(), 1) == b"public page"
    assert renderer.response_body(reply(status=302, headers={"location": "https://example.com/end"}), 1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": True},
        {"id": 2},
        {"status": True},
        {"status": 101},
        {"status": 600},
        {"headers": {"set-cookie": "session=private"}},
        {"headers": {"authorization": "private"}},
        {"headers": {"content-type": "text/html\r\nx-injected: yes"}},
        {"headers": {"content-type": "x" * 2001}},
        {"headers": []},
        {"body": "not base64!"},
        {"body": False},
        {"unexpected": "unsafe"},
    ],
)
def test_protocol_rejects_unexpected_or_unsafe_response(overrides):
    with pytest.raises(ValueError):
        renderer.response_body(reply(**overrides), 1)


def test_response_size_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(renderer, "MAX_RESPONSE", 4)
    with pytest.raises(ValueError, match="limit"):
        renderer.response_body(reply(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["", "[]\n", "{}", "{" + "x" * 80 + "}\n"])
async def test_protocol_requires_bounded_complete_object(monkeypatch, payload):
    monkeypatch.setattr(renderer.sys, "stdin", io.StringIO(payload))
    monkeypatch.setattr(renderer, "MAX_LINE", 64)
    with pytest.raises(ValueError):
        await renderer.receive()
