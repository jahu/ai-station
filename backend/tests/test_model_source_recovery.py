"""Tiny content-pinned objects and fake publisher metadata; no real downloads."""

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager

import httpx
import pytest
from app import model_download_files as files
from app import model_source_recovery as recovery

CONTENT = b"abcdefgh"
REPO = "publisher/reviewed-model"
OLD = "1" * 40
NEW = "2" * 40
URL = f"https://huggingface.co/{REPO}/resolve/{OLD}/weights.gguf"
REPLACEMENT = f"https://huggingface.co/{REPO}/resolve/{NEW}/weights.gguf"
API = f"https://huggingface.co/api/models/{REPO}/revision/main?blobs=true"


def spec(*urls):
    return files.FileSpec(sha256=hashlib.sha256(CONTENT).hexdigest(), size_bytes=8, urls=urls or (URL,))


def metadata():
    return {
        "sha": NEW,
        "siblings": [{"rfilename": "weights.gguf", "size": 8, "lfs": {"sha256": spec().sha256, "size": 8}}],
    }


def answer(status=200, body=CONTENT, **headers):
    return httpx.Response(
        status, headers=headers, stream=httpx.ByteStream(body), request=httpx.Request("GET", URL)
    )


def sources(monkeypatch, replies):
    calls = []

    @asynccontextmanager
    async def response(url, offset, check):
        check()
        calls.append((url, offset))
        result = replies.pop(0)
        try:
            yield result
        finally:
            await result.aclose()

    monkeypatch.setattr(files, "response", response)
    return calls


def obtain(root, pinned=None, *, check=lambda: None, recovered=lambda url: None):
    return asyncio.run(
        files.obtain(
            root, pinned or spec(), check=check, progress=lambda *_: None, source_recovered=recovered
        )
    )


def partial(root, content=b"abcd"):
    folder = files.directory(root)
    path = folder / (spec().sha256 + ".part")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
    return path


@pytest.mark.parametrize("status", [404, 410])
def test_stale_source_recovers_only_identical_bytes_and_resumes_partial(tmp_path, monkeypatch, status):
    saved = partial(tmp_path)
    pinned = spec()
    frozen = pinned.model_dump(mode="json")
    calls = sources(
        monkeypatch,
        [
            answer(status),
            answer(body=json.dumps(metadata()).encode()),
            answer(206, b"efgh", **{"content-range": "bytes 4-7/8"}),
        ],
    )
    events = []
    final = obtain(tmp_path, pinned, recovered=events.append)
    assert final.read_bytes() == CONTENT and not saved.exists()
    assert final.stat().st_mode & 0o222 == 0
    assert pinned.model_dump(mode="json") == frozen
    assert calls == [(URL, 4), (API, 0), (REPLACEMENT, 4)]
    assert events == [REPLACEMENT]
    assert obtain(tmp_path) == final and len(calls) == 3  # Cache needs no metadata.


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "size",
        "bool_size",
        "file_size",
        "filename",
        "no_lfs",
        "duplicate",
        "missing",
        "revision",
        "same_revision",
        "siblings",
        "not_object",
    ],
)
def test_changed_ambiguous_or_missing_identity_cannot_replace_the_reviewed_model(
    tmp_path, monkeypatch, mutation
):
    data = metadata()
    item = data["siblings"][0]
    if mutation == "hash":
        item["lfs"]["sha256"] = "f" * 64
    elif mutation == "size":
        item["lfs"]["size"] = 9
    elif mutation == "bool_size":
        item["lfs"]["size"] = True
    elif mutation == "file_size":
        item["size"] = 9
    elif mutation == "filename":
        item["rfilename"] = "replacement.gguf"
    elif mutation == "no_lfs":
        item.pop("lfs")
    elif mutation == "duplicate":
        data["siblings"].append(item.copy())
    elif mutation == "missing":
        data["siblings"] = []
    elif mutation == "revision":
        data["sha"] = "main"
    elif mutation == "same_revision":
        data["sha"] = OLD
    elif mutation == "siblings":
        data["siblings"] = {}
    elif mutation == "not_object":
        data = []
    saved = partial(tmp_path)
    calls = sources(monkeypatch, [answer(404), answer(body=json.dumps(data).encode())])
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path)
    assert calls == [(URL, 4), (API, 0)] and saved.read_bytes() == b"abcd"
    assert not (saved.parent / spec().sha256).exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://elsewhere.example/owner/repo/resolve/" + OLD + "/weights.gguf",
        URL.replace("https:", "http:"),
        URL + "?token=not-sent",
        URL + "#fragment",
        URL.replace("huggingface.co", "huggingface.co:443"),
        URL.replace("huggingface.co", "user@huggingface.co"),
        URL.replace(OLD, "main"),
        URL.replace("weights.gguf", "../weights.gguf"),
        URL.replace("weights.gguf", "%2e%2e/weights.gguf"),
        URL.replace("weights.gguf", "sub%2fweights.gguf"),
        URL.replace("weights.gguf", "%0aweights.gguf"),
        URL.replace("weights.gguf", "sub%5cweights.gguf"),
        URL.replace("weights.gguf", "%ff"),
        "https://[invalid/weights.gguf",
        URL + "\n",
    ],
)
def test_unreviewable_locator_never_becomes_an_api_request(url):
    assert recovery.source_identity(url) is None


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_auth_rate_limit_and_transient_file_errors_do_not_trigger_metadata(tmp_path, monkeypatch, status):
    calls = sources(monkeypatch, [answer(status)])
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path)
    assert calls == [(URL, 0)]


def test_original_success_and_non_hf_missing_source_do_not_fetch_metadata(tmp_path, monkeypatch):
    calls = sources(monkeypatch, [answer()])
    assert obtain(tmp_path).read_bytes() == CONTENT and calls == [(URL, 0)]
    other = "https://models.example.com/reviewed.gguf"
    calls = sources(monkeypatch, [answer(404)])
    (tmp_path / "other").mkdir()
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path / "other", spec(other))
    assert calls == [(other, 0)]


@pytest.mark.parametrize(
    "body,headers",
    [
        (b"invalid json", {}),
        (b"\xff", {}),
        (b"{}", {"content-length": "9999999999"}),
        (b"{}", {"content-encoding": "gzip"}),
        (b"x" * 1025, {}),
    ],
)
def test_invalid_or_unbounded_metadata_preserves_partial(tmp_path, monkeypatch, body, headers):
    saved = partial(tmp_path)
    monkeypatch.setattr(recovery, "MAX_METADATA_BYTES", 1024)
    calls = sources(monkeypatch, [answer(404), answer(body=body, **headers)])
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path)
    assert len(calls) == 2 and saved.read_bytes() == b"abcd"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_unavailable_metadata_is_bounded_and_does_not_fall_back_to_other_repositories(
    tmp_path, monkeypatch, status
):
    calls = sources(monkeypatch, [answer(404), answer(status)])
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path)
    assert calls == [(URL, 0), (API, 0)]


def test_recovered_bytes_still_require_the_frozen_hash_and_do_not_retry_forever(tmp_path, monkeypatch):
    calls = sources(
        monkeypatch, [answer(404), answer(body=json.dumps(metadata()).encode()), answer(body=b"xxxxxxxx")]
    )
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path)
    assert len(calls) == 3
    assert (files.directory(tmp_path) / (spec().sha256 + ".part")).read_bytes() == b""
    assert not (files.directory(tmp_path) / spec().sha256).exists()


def test_cancellation_storage_and_lease_errors_from_checks_are_not_swallowed(tmp_path, monkeypatch):
    saved = partial(tmp_path)
    calls = sources(monkeypatch, [answer(404), answer(body=json.dumps(metadata()).encode())])

    def check():
        if len(calls) >= 2:
            raise ValueError("Run authority or storage admission changed")

    with pytest.raises(ValueError, match="authority or storage"):
        obtain(tmp_path, check=check)
    assert calls == [(URL, 4), (API, 0)] and saved.read_bytes() == b"abcd"


def test_recovery_queries_each_missing_repository_once_and_preserves_unicode_filename(monkeypatch):
    filename = "subdir/zażółć weights.gguf"
    encoded = "subdir/za%C5%BC%C3%B3%C5%82%C4%87%20weights.gguf"
    first = URL.replace("weights.gguf", encoded)
    second = first.replace(OLD, "3" * 40)
    pinned = spec(first, second)
    data = metadata()
    data["siblings"][0]["rfilename"] = filename
    calls = sources(monkeypatch, [answer(body=json.dumps(data).encode())])
    result = asyncio.run(
        recovery.recover_sources(
            pinned, urls=pinned.urls, check=lambda: None, response=files.response, wait=files._wait
        )
    )
    assert result == (REPLACEMENT.replace("weights.gguf", encoded),)
    assert calls == [(API, 0)]


@pytest.mark.parametrize("failure", ["redirect", "dns"])
def test_metadata_uses_the_existing_pinned_https_boundary_without_private_fallback(
    tmp_path, monkeypatch, failure
):
    from app.providers import ProviderError

    original = httpx.AsyncClient
    calls, dns = [], []

    async def addresses(host):
        assert host == "huggingface.co"
        dns.append(host)
        if len(dns) == 2 and failure == "dns":
            raise ProviderError("Metadata resolved to a private address")
        return ["93.184.216.34"]

    async def handler(request):
        calls.append(request)
        if request.url.path.startswith("/api/models/"):
            return httpx.Response(302, headers={"location": "https://127.0.0.1/admin"})
        return httpx.Response(404)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(files, "public_addresses", addresses)
    monkeypatch.setattr(files.httpx, "AsyncClient", client)
    with pytest.raises(ValueError if failure == "redirect" else ProviderError):
        obtain(tmp_path)
    assert len(calls) == (2 if failure == "redirect" else 1)
    assert len(dns) == 2
    assert all(
        r.url.host == "93.184.216.34"
        and r.headers["Host"] == "huggingface.co"
        and r.extensions["sni_hostname"] == "huggingface.co"
        for r in calls
    )
    assert all("Authorization" not in r.headers and "Cookie" not in r.headers for r in calls)
