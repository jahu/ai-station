import asyncio
import time

import httpx
import pytest
from ai_station_runner import browser_http as broker


def mock_client(monkeypatch, handler, dns=None):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(broker, "public_addresses", dns or (lambda host: ["93.184.216.34"]))


@pytest.mark.asyncio
async def test_get_pins_ip_keeps_tls_and_drops_response_secrets(monkeypatch):
    def handler(request):
        assert request.method == "GET" and request.url.host == "93.184.216.34"
        assert request.headers["host"] == "www.example.com"
        assert request.extensions["sni_hostname"] == "www.example.com"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        return httpx.Response(
            200,
            headers={
                "content-type": "text/javascript",
                "set-cookie": "private",
                "content-security-policy": "default-src 'self'",
            },
            content=b"javascript",
        )

    mock_client(monkeypatch, handler)
    status, headers, body = await broker.fetch_resource(
        "https://www.example.com/a.js", broker.BrowserBudget()
    )
    assert status == 200 and body == b"javascript" and "set-cookie" not in headers
    assert headers["content-security-policy"] == "default-src 'self'"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/", "file:///etc/passwd", "http://[ff00::1]/", "https://u:p@example.com/"]
)
async def test_private_targets_never_connect(monkeypatch, url):
    def fail(*a, **k):
        raise AssertionError("Unsafe target reached network")

    mock_client(monkeypatch, fail, dns=fail)
    with pytest.raises(ValueError, match="public"):
        await broker.fetch_resource(url, broker.BrowserBudget())


@pytest.mark.asyncio
async def test_redirect_private_dns_rejected_before_chromium_sees_location(monkeypatch):
    def dns(host):
        if host == "evil.example":
            raise ValueError("private DNS")
        return ["93.184.216.34"]

    mock_client(
        monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://evil.example/"}), dns
    )
    with pytest.raises(ValueError, match="private"):
        await broker.fetch_resource("https://www.example.com/", broker.BrowserBudget())


@pytest.mark.asyncio
async def test_redirect_is_returned_to_browser_with_resolved_location(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "/next"})

    mock_client(monkeypatch, handler)
    status, headers, _ = await broker.fetch_resource("https://www.example.com/start", broker.BrowserBudget())
    assert status == 302 and headers["location"] == "https://www.example.com/next" and len(calls) == 1


@pytest.mark.asyncio
async def test_byte_request_and_time_limits_fail_closed(monkeypatch):
    mock_client(monkeypatch, lambda r: httpx.Response(200, content=b"too large"))
    for budget in [
        broker.BrowserBudget(remaining=2),
        broker.BrowserBudget(requests=0),
        broker.BrowserBudget(deadline=time.monotonic() - 1),
    ]:
        with pytest.raises(ValueError):
            await broker.fetch_resource("https://www.example.com/", budget)


@pytest.mark.asyncio
async def test_cancellation_closes_pending_broker_request(monkeypatch):
    canceled = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.sleep(30)
        finally:
            canceled.set()

    mock_client(monkeypatch, handler)
    pending = asyncio.create_task(broker.fetch_resource("https://www.example.com/", broker.BrowserBudget()))
    await asyncio.sleep(0.1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert canceled.is_set()


@pytest.mark.asyncio
async def test_rejected_oversized_response_still_consumes_page_budget(monkeypatch):
    monkeypatch.setattr(broker, "MAX_RESPONSE", 4)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"123456")

    mock_client(monkeypatch, handler)
    budget = broker.BrowserBudget(remaining=10)
    with pytest.raises(ValueError):
        await broker.fetch_resource("https://www.example.com/large", budget)
    assert budget.remaining == 4
    with pytest.raises(ValueError):
        await broker.fetch_resource("https://www.example.com/large-again", budget)
    assert budget.remaining == 0
    with pytest.raises(ValueError):
        await broker.fetch_resource("https://www.example.com/not-fetched", budget)
    assert len(calls) == 2
