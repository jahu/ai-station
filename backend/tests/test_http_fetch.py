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
        assert str(request.url) == "https://93.184.216.34/"
        assert request.headers["host"] == "www.example.com"
        assert request.extensions["sni_hostname"] == "www.example.com"
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
        if str(request.url) == "https://93.184.216.34/go":
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


@pytest.mark.parametrize(
    "url",
    [
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "http://[::ffff:224.0.0.1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[2002:7f00:1::]/",
    ],
)
def test_public_url_rejects_multicast_and_transition_routing(url):
    assert http_fetch.public_url(url) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "224.0.0.1",
        "ff0e::1",
        "127.0.0.1",
        "10.2.3.4",
        "169.254.169.254",
        "::ffff:224.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
    ],
)
async def test_dns_rejects_mixed_public_and_unsafe_answers(monkeypatch, address):
    monkeypatch.setattr(
        http_fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", (ip, 0)) for ip in ["93.184.216.34", address]],
    )
    with pytest.raises(ValueError, match="non-public"):
        await http_fetch.fetch_public("https://www.example.com/")


@pytest.mark.asyncio
async def test_fetch_pins_first_lookup_and_preserves_url(monkeypatch):
    lookups = []

    def dns(host, *args, **kwargs):
        lookups.append(host)
        address = "93.184.216.34" if len(lookups) == 1 else "127.0.0.1"
        return [(0, 0, 0, "", (address, 0))]

    def handle(request):
        assert str(request.url) == "https://93.184.216.34/a?x=1"
        assert request.headers["host"] == "www.example.com"
        assert request.extensions["sni_hostname"] == "www.example.com"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"public")

    _client(handle, monkeypatch)
    monkeypatch.setattr(http_fetch.socket, "getaddrinfo", dns)
    result = await http_fetch.fetch_public("https://www.example.com/a?x=1")
    assert lookups == ["www.example.com"]
    assert result["url"] == "https://www.example.com/a?x=1"


@pytest.mark.asyncio
async def test_redirect_resolves_and_blocks_new_host_before_connecting(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "https://evil.example/secret"})

    _client(handle, monkeypatch)
    monkeypatch.setattr(
        http_fetch.socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (0, 0, 0, "", (("127.0.0.1" if host == "evil.example" else "93.184.216.34"), 0))
        ],
    )
    with pytest.raises(ValueError, match="non-public"):
        await http_fetch.fetch_public("https://www.example.com/")
    assert calls == ["www.example.com"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "redirect", ["https://other.example/end", "http://www.example.com/end", "https://www.example.com:80/end"]
)
async def test_redirect_strips_credentials_and_uses_new_tls_pool(monkeypatch, redirect):
    requests, clients = [], []
    original = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302, headers={"location": redirect, "set-cookie": "session=private; Path=/"}
            )
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"end")

    def client(**kwargs):
        made = original(**kwargs, transport=httpx.MockTransport(handle))
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(
        http_fetch.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))]
    )
    result = await http_fetch.fetch_public(
        "https://www.example.com/start",
        extra_headers={"Authorization": "Bearer private", "X-API-Key": "private", "Cookie": "saved=private"},
    )
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert requests[0].headers["authorization"] == "Bearer private"
    assert all(key not in requests[1].headers for key in ("authorization", "x-api-key", "cookie"))
    assert requests[1].headers["host"] == httpx.URL(redirect).netloc.decode()
    assert requests[1].extensions["sni_hostname"] == httpx.URL(redirect).host
    assert result["url"] == redirect


@pytest.mark.asyncio
async def test_same_origin_redirect_keeps_authorization_without_response_cookies(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "/end", "set-cookie": "session=private; Path=/"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"end")

    _client(handle, monkeypatch)
    await http_fetch.fetch_public(
        "https://www.example.com/start", extra_headers={"Authorization": "Bearer private"}
    )
    assert requests[1].headers["authorization"] == "Bearer private"
    assert "cookie" not in requests[1].headers


@pytest.mark.asyncio
async def test_fetch_pins_ipv6_and_preserves_explicit_authority(monkeypatch):
    def handle(request):
        assert str(request.url) == "https://[2606:4700:4700::1111]:80/a?x=1"
        assert request.headers["host"] == "www.example.com:80"
        assert request.extensions["sni_hostname"] == "www.example.com"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"public")

    _client(handle, monkeypatch, address="2606:4700:4700::1111")
    result = await http_fetch.fetch_public("https://www.example.com:80/a?x=1")
    assert result["status"] == 200


@pytest.mark.asyncio
async def test_actual_transport_connects_checked_ip_with_verified_tls_hostname(monkeypatch):
    import ssl

    from httpcore._backends.auto import AutoBackend
    from httpcore._backends.mock import AsyncMockStream

    connected, tls, written = [], [], []

    class Stream(AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls.append(server_hostname)
            assert ssl_context.check_hostname is True
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            return self

        async def write(self, buffer, timeout=None):
            written.append(buffer)

    async def connect(self, host, port, **kwargs):
        connected.append((host, port))
        return Stream([b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nContent-Type: text/plain\r\n\r\npublic"])

    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    monkeypatch.setattr(
        http_fetch.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))]
    )
    result = await http_fetch.fetch_public("https://www.example.com/a")
    assert connected == [("93.184.216.34", 443)]
    assert tls == ["www.example.com"]
    assert b"Host: www.example.com\r\n" in b"".join(written)
    assert result["text"] == "public"


@pytest.mark.asyncio
async def test_connect_failure_tries_another_checked_ip_without_new_dns(monkeypatch):
    calls, lookups = [], []

    def handle(request):
        calls.append(request.url.host)
        if len(calls) == 1:
            raise httpx.ConnectError("first address unavailable")
        assert request.headers["host"] == "www.example.com"
        assert request.extensions["sni_hostname"] == "www.example.com"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"public")

    def dns(host, *args, **kwargs):
        lookups.append(host)
        return [(0, 0, 0, "", (ip, 0)) for ip in ["93.184.216.34", "1.1.1.1"]]

    _client(handle, monkeypatch)
    monkeypatch.setattr(http_fetch.socket, "getaddrinfo", dns)
    assert (await http_fetch.fetch_public("https://www.example.com/"))["status"] == 200
    assert calls == ["93.184.216.34", "1.1.1.1"] and lookups == ["www.example.com"]
