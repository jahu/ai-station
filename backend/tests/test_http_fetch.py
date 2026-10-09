import httpx
import pytest
from app import http_fetch
from app.providers import ProviderError


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/index",
        "http://10.0.0.1/secret",
        "http://169.254.169.254/latest",
        "http://[::1]/",
        "file:///etc/passwd",
        "https://example.com:8443/",
        "https://user:pass@example.com/",
        "http://metadata.google.internal/",
        "not-a-url",
        "https://example.local/page",
        "https://example.com/\nattack",
    ],
)
def test_public_url_rejects_private_and_special_targets(url):
    assert http_fetch.public_url(url) is None


def test_reviewed_urls_require_unique_public_http():
    assert http_fetch.reviewed_urls([]) == []
    assert http_fetch.reviewed_urls(["https://www.example.com/a"]) == ["https://www.example.com/a"]
    with pytest.raises(ValueError, match="port 80 or 443"):
        http_fetch.reviewed_urls(["http://127.0.0.1/admin"])
    with pytest.raises(ValueError, match="Duplicate"):
        http_fetch.reviewed_urls(["https://www.example.com/", "https://www.example.com/"])
    with pytest.raises(ValueError, match="at most three"):
        http_fetch.reviewed_urls([f"https://www.example.com/{i}" for i in range(4)])


def test_prompt_public_urls_extracts_http_and_skips_private():
    text = "Fetch https://www.example.com/ and http://127.0.0.1/admin plus https://docs.example.org/a."
    assert http_fetch.prompt_public_urls(text) == [
        "https://www.example.com/",
        "https://docs.example.org/a",
    ]


@pytest.mark.asyncio
async def test_public_addresses_reject_loopback_after_dns(monkeypatch):
    monkeypatch.setattr(
        http_fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="non-public"):
        await http_fetch.public_addresses("evil.example")


def _client(handle, monkeypatch, address="93.184.216.34"):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(
        http_fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", (address, 0))],
    )


@pytest.mark.asyncio
async def test_fetch_public_returns_html_text_and_same_origin_links(monkeypatch):
    html = (
        "<html><head><title>Kora</title><script>secret()</script></head>"
        '<body><p>Timber company</p><a href="/about">About</a>'
        '<a href="https://other.example/x">skip</a></body></html>'
    )

    def handle(request):
        assert request.method == "GET"
        assert str(request.url) == "https://www.example.com/"
        assert request.headers["user-agent"] == "AI-Station-agent/1"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html.encode())

    _client(handle, monkeypatch)
    result = await http_fetch.fetch_public("https://www.example.com/")
    assert result["status"] == 200
    assert "Timber company" in result["text"]
    assert "secret()" not in result["text"]
    assert result["links"] == ["https://www.example.com/about"]
    assert result["untrusted"] is True and result["bounded"] is True


@pytest.mark.asyncio
async def test_fetch_public_refuses_redirect_to_loopback(monkeypatch):
    def handle(request):
        if str(request.url) == "https://example.com/go":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        raise AssertionError(request.url)

    _client(handle, monkeypatch)
    with pytest.raises(ValueError, match="non-public"):
        await http_fetch.fetch_public("https://example.com/go")


@pytest.mark.asyncio
async def test_fetch_public_skips_binary(monkeypatch):
    def handle(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")

    _client(handle, monkeypatch, address="1.1.1.1")
    result = await http_fetch.fetch_public("https://cdn.example/hero.png")
    assert result["skipped"] == "binary" and result["text"] == ""


@pytest.mark.asyncio
async def test_fetch_public_network_errors_fail_closed(monkeypatch):
    def handle(request):
        raise httpx.ConnectError("down")

    _client(handle, monkeypatch)
    with pytest.raises(ProviderError, match="could not complete"):
        await http_fetch.fetch_public("https://www.example.com/")
