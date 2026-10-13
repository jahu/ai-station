import json

import httpx
import pytest
from ai_station_runner import public_http


class _Response:
    def __init__(self, status=200, headers=None, body=b"", location=None):
        self.status_code = status
        self.headers = dict(headers or {})
        if location:
            self.headers["location"] = location
        self._body = body

    def iter_bytes(self):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


class _Client:
    def __init__(self, handler, **_kwargs):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        return self.handler(method, url, **kwargs)


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
    ],
)
def test_public_url_rejects_private_and_special_targets(url):
    assert public_http.public_url(url) is None


def test_public_url_accepts_https_example():
    assert public_http.public_url("https://www.koratimber.com/") == "https://www.koratimber.com/"


def test_prompt_public_urls_extracts_http_and_skips_private():
    text = (
        "Zbuduj stronę firmy Kora Timber ( https://www.koratimber.com/ ) "
        "oraz http://127.0.0.1/admin i https://example.com/docs."
    )
    assert public_http.prompt_public_urls(text) == [
        "https://www.koratimber.com/",
        "https://example.com/docs",
    ]


def test_public_addresses_reject_loopback(monkeypatch):
    monkeypatch.setattr(
        public_http.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="non-public"):
        public_http.public_addresses("evil.example")


def test_fetch_public_returns_html_text_and_same_origin_links(monkeypatch):
    html = (
        b"<html><head><title>Kora</title><script>secret()</script></head>"
        b'<body><p>Timber company</p><a href="/about">About</a>'
        b'<a href="https://other.example/x">skip</a></body></html>'
    )

    def handler(method, url, **_kwargs):
        assert method == "GET"
        assert str(url) == "https://93.184.216.34/"
        assert _kwargs["headers"]["Host"] == "www.koratimber.com"
        assert _kwargs["extensions"]["sni_hostname"] == "www.koratimber.com"
        return _Response(headers={"content-type": "text/html"}, body=html)

    monkeypatch.setattr(public_http.httpx, "Client", lambda **k: _Client(handler, **k))
    monkeypatch.setattr(
        public_http.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))],
    )
    result = public_http.fetch_public("https://www.koratimber.com/")
    assert result["status"] == 200
    assert "Timber company" in result["text"]
    assert "secret()" not in result["text"]
    assert result["links"] == ["https://www.koratimber.com/about"]
    assert result["untrusted"] is True


def test_fetch_public_refuses_redirect_to_loopback(monkeypatch):
    def handler(method, url, **_kwargs):
        if str(url) == "https://93.184.216.34/go":
            return _Response(status=302, location="http://127.0.0.1/admin")
        raise AssertionError(url)

    monkeypatch.setattr(public_http.httpx, "Client", lambda **k: _Client(handler, **k))
    monkeypatch.setattr(
        public_http.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))],
    )
    with pytest.raises(ValueError, match="non-public"):
        public_http.fetch_public("https://example.com/go")


def test_fetch_public_skips_binary(monkeypatch):
    def handler(method, url, **_kwargs):
        return _Response(headers={"content-type": "image/png"}, body=b"\x89PNG")

    monkeypatch.setattr(public_http.httpx, "Client", lambda **k: _Client(handler, **k))
    monkeypatch.setattr(
        public_http.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("1.1.1.1", 0))],
    )
    result = public_http.fetch_public("https://cdn.example/hero.png")
    assert result["skipped"] == "binary" and result["text"] == ""


def test_search_web_returns_public_sources(monkeypatch):
    payload = json.dumps(
        {
            "results": [
                {
                    "title": "Kora Timber",
                    "url": "https://www.koratimber.com/",
                    "content": "Polish timber company",
                },
                {"title": "local", "url": "http://127.0.0.1/x", "content": "nope"},
            ]
        }
    ).encode()

    def handler(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/search")
        return _Response(headers={"content-type": "application/json"}, body=payload)

    monkeypatch.setattr(
        public_http,
        "get_settings",
        lambda: type("S", (), {"web_search_url": "http://127.0.0.1:8878"})(),
    )
    monkeypatch.setattr(public_http.httpx, "Client", lambda **k: _Client(handler, **k))
    result = public_http.search_web("Kora Timber")
    assert result["sources"][0]["url"] == "https://www.koratimber.com/"
    assert len(result["sources"]) == 1


def test_proposal_references_keep_fetch_text_and_search_snippets():
    refs = public_http.proposal_references(
        [
            {
                "request": {"tool": "fetch_url", "url": "https://www.koratimber.com/"},
                "result": {
                    "url": "https://www.koratimber.com/",
                    "text": "ul. Przybyszewskiego 193, Łódź",
                },
            },
            {
                "request": {"tool": "list_files", "prefix": "", "offset": 0},
                "result": {"files": ["index.html"]},
            },
            {
                "request": {"tool": "web_search", "query": "Kora Timber"},
                "result": {"query": "Kora Timber", "sources": [{"url": "https://www.koratimber.com/"}]},
            },
        ]
    )
    assert refs[0]["text"].startswith("ul. Przybyszewskiego")
    assert refs[1]["sources"][0]["url"] == "https://www.koratimber.com/"
    assert public_http.proposal_references([]) == []


def test_search_web_requires_configured_endpoint(monkeypatch):
    monkeypatch.setattr(
        public_http,
        "get_settings",
        lambda: type("S", (), {"web_search_url": ""})(),
    )
    with pytest.raises(ValueError, match="not configured"):
        public_http.search_web("query")


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
    assert public_http.public_url(url) is None


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
def test_dns_rejects_mixed_public_and_unsafe_answers(monkeypatch, address):
    monkeypatch.setattr(
        public_http.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", (ip, 0)) for ip in ["93.184.216.34", address]],
    )
    with pytest.raises(ValueError, match="non-public"):
        public_http.fetch_public("https://www.example.com/")


def test_native_fetch_pins_dns_once_and_preserves_original_url(monkeypatch):
    original = httpx.Client
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

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(public_http.socket, "getaddrinfo", dns)
    result = public_http.fetch_public("https://www.example.com/a?x=1")
    assert lookups == ["www.example.com"]
    assert result["url"] == "https://www.example.com/a?x=1"


def test_native_redirect_revalidates_host_and_does_not_reuse_tls_pool(monkeypatch):
    original = httpx.Client
    clients, requests, lookups = [], [], []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"location": "https://other.example/end", "set-cookie": "session=private; Path=/"},
            )
        assert request.extensions["sni_hostname"] == "other.example"
        assert request.headers["host"] == "other.example"
        assert "cookie" not in request.headers
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"end")

    def client(**kwargs):
        made = original(**kwargs, transport=httpx.MockTransport(handle))
        clients.append(made)
        return made

    def dns(host, *args, **kwargs):
        lookups.append(host)
        return [(0, 0, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(public_http.socket, "getaddrinfo", dns)
    result = public_http.fetch_public("https://www.example.com/start")
    assert lookups == ["www.example.com", "other.example"]
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert result["url"] == "https://other.example/end"


def test_native_redirect_rejects_private_dns_before_connection(monkeypatch):
    original = httpx.Client
    calls = []

    def handle(request):
        calls.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "https://evil.example/secret"})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(
        public_http.socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (0, 0, 0, "", (("127.0.0.1" if host == "evil.example" else "93.184.216.34"), 0))
        ],
    )
    with pytest.raises(ValueError, match="non-public"):
        public_http.fetch_public("https://www.example.com/")
    assert calls == ["www.example.com"]


def test_native_ipv6_pin_preserves_authority(monkeypatch):
    original = httpx.Client

    def handle(request):
        assert str(request.url) == "https://[2606:4700:4700::1111]:80/a?x=1"
        assert request.headers["host"] == "www.example.com:80"
        assert request.extensions["sni_hostname"] == "www.example.com"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"public")

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(
        public_http.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("2606:4700:4700::1111", 0))]
    )
    assert public_http.fetch_public("https://www.example.com:80/a?x=1")["status"] == 200


def test_actual_native_transport_uses_checked_ip_and_verified_tls_hostname(monkeypatch):
    import ssl

    from httpcore._backends.mock import MockStream
    from httpcore._backends.sync import SyncBackend

    connected, tls, written = [], [], []

    class Stream(MockStream):
        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls.append(server_hostname)
            assert ssl_context.check_hostname is True
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            return self

        def write(self, buffer, timeout=None):
            written.append(buffer)

    def connect(self, host, port, **kwargs):
        connected.append((host, port))
        return Stream([b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nContent-Type: text/plain\r\n\r\npublic"])

    monkeypatch.setattr(SyncBackend, "connect_tcp", connect)
    monkeypatch.setattr(
        public_http.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))]
    )
    result = public_http.fetch_public("https://www.example.com/a")
    assert connected == [("93.184.216.34", 443)]
    assert tls == ["www.example.com"]
    assert b"Host: www.example.com\r\n" in b"".join(written)
    assert result["text"] == "public"


def test_native_connect_failure_tries_remaining_checked_ip_without_new_dns(monkeypatch):
    original = httpx.Client
    calls, lookups = [], []

    def handle(request):
        calls.append(request.url.host)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("first address unavailable")
        assert request.headers["host"] == "www.example.com"
        assert request.extensions["sni_hostname"] == "www.example.com"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"public")

    def dns(host, *args, **kwargs):
        lookups.append(host)
        return [(0, 0, 0, "", (ip, 0)) for ip in ["93.184.216.34", "1.1.1.1"]]

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(public_http.socket, "getaddrinfo", dns)
    assert public_http.fetch_public("https://www.example.com/")["status"] == 200
    assert calls == ["93.184.216.34", "1.1.1.1"] and lookups == ["www.example.com"]
