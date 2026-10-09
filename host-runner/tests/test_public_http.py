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
        assert url == "https://www.koratimber.com/"
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
        if url == "https://example.com/go":
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
