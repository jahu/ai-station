"""Tiny synthetic model objects and mocked HTTPS; no downloads or inference."""

import asyncio
import hashlib
import os
from contextlib import asynccontextmanager

import httpx
import pytest
from app import model_download_files as files

CONTENT = b"abcdefgh"
URL = "https://models.example.com/revision/weights.gguf"


def private_file(path, value):
    # Reproduce the downloader's mode regardless of the workstation's umask.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(value)
    return path


def spec(*urls):
    return files.FileSpec(
        sha256=hashlib.sha256(CONTENT).hexdigest(), size_bytes=len(CONTENT), urls=urls or [URL]
    )


def obtain(root, pinned=None, *, check=lambda: None, progress=lambda done, total: None):
    return asyncio.run(files.obtain(root, pinned or spec(), check=check, progress=progress))


def answer(status=200, body=CONTENT, **headers):
    return httpx.Response(
        status, headers=headers, stream=httpx.ByteStream(body), request=httpx.Request("GET", URL)
    )


def source(monkeypatch, responses):
    offsets = []

    @asynccontextmanager
    async def response(url, offset, check):
        offsets.append((url, offset))
        result = responses.pop(0)
        try:
            yield result
        finally:
            await result.aclose()

    monkeypatch.setattr(files, "response", response)
    return offsets


def test_hash_verified_immutable_file_is_published_once_and_reused_without_network(tmp_path, monkeypatch):
    offsets = source(monkeypatch, [answer()])
    progress = []
    result = obtain(tmp_path, progress=lambda current, total: progress.append((current, total)))
    assert result.read_bytes() == CONTENT and result.name == spec().sha256
    assert result.stat().st_mode & 0o222 == 0
    assert progress[-1] == (8, 8)
    assert obtain(tmp_path) == result
    assert offsets == [(URL, 0)]
    assert not result.with_suffix(".part").exists()


def test_saved_prefix_resumes_at_exact_server_confirmed_range(tmp_path, monkeypatch):
    pinned = spec()
    folder = files.directory(tmp_path)
    private_file(folder / (pinned.sha256 + ".part"), CONTENT[:4])
    offsets = source(
        monkeypatch, [answer(206, CONTENT[4:], **{"content-range": "bytes 4-7/8", "content-length": "4"})]
    )
    assert obtain(tmp_path).read_bytes() == CONTENT
    assert offsets == [(URL, 4)]


def test_server_without_range_support_restarts_instead_of_appending(tmp_path, monkeypatch):
    folder = files.directory(tmp_path)
    private_file(folder / (spec().sha256 + ".part"), CONTENT[:4])
    source(monkeypatch, [answer(200)])
    assert obtain(tmp_path).read_bytes() == CONTENT


@pytest.mark.parametrize("range_header", ["bytes 0-7/8", "bytes 4-8/9", "bytes 4-6/8", "garbage"])
def test_wrong_content_range_cannot_append_or_publish(tmp_path, monkeypatch, range_header):
    folder = files.directory(tmp_path)
    partial = folder / (spec().sha256 + ".part")
    private_file(partial, CONTENT[:4])
    source(monkeypatch, [answer(206, CONTENT[4:], **{"content-range": range_header})])
    with pytest.raises(ValueError, match="byte range"):
        obtain(tmp_path)
    assert partial.read_bytes() == CONTENT[:4]
    assert not (folder / spec().sha256).exists()


def test_failed_hash_is_not_installed_and_only_identical_reviewed_mirror_can_recover(tmp_path, monkeypatch):
    mirror = "https://mirror.example.com/pinned.gguf"
    offsets = source(monkeypatch, [answer(body=b"XXXXXXXX"), answer()])
    assert obtain(tmp_path, spec(URL, mirror)).read_bytes() == CONTENT
    assert offsets == [(URL, 0), (mirror, 0)]


def test_stale_link_uses_only_the_next_reviewed_url_with_same_size_and_hash(tmp_path, monkeypatch):
    mirror = "https://mirror.example.com/pinned.gguf"
    source(monkeypatch, [answer(404, b""), answer()])
    assert obtain(tmp_path, spec(URL, mirror)).read_bytes() == CONTENT


def test_failed_hash_can_be_retried_without_a_poisoned_complete_partial(tmp_path, monkeypatch):
    source(monkeypatch, [answer(body=b"XXXXXXXX"), answer()])
    with pytest.raises(files.SourceUnavailable):
        obtain(tmp_path)
    assert obtain(tmp_path).read_bytes() == CONTENT


def test_existing_damaged_file_is_never_overwritten(tmp_path, monkeypatch):
    folder = files.directory(tmp_path)
    final = folder / spec().sha256
    private_file(final, b"operator-owned unrelated data")
    source(monkeypatch, [])
    with pytest.raises(files.VerificationFailed):
        obtain(tmp_path)
    assert final.read_bytes() == b"operator-owned unrelated data"


@pytest.mark.parametrize("kind", ["directory", "partial", "final", "lock"])
def test_symlink_escape_cannot_write_an_external_file(tmp_path, monkeypatch, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "protected"
    protected.write_bytes(b"untouched")
    if kind == "directory":
        (tmp_path / "models").symlink_to(outside, target_is_directory=True)
    else:
        folder = files.directory(tmp_path)
        suffix = {"partial": ".part", "final": "", "lock": ".lock"}[kind]
        (folder / (spec().sha256 + suffix)).symlink_to(protected)
    source(monkeypatch, [answer()])
    with pytest.raises((ValueError, OSError)):
        obtain(tmp_path)
    assert protected.read_bytes() == b"untouched"


def test_hard_linked_partial_is_not_truncated_or_appended(tmp_path, monkeypatch):
    protected = tmp_path / "protected"
    protected.write_bytes(b"safe")
    os.link(protected, files.directory(tmp_path) / (spec().sha256 + ".part"))
    source(monkeypatch, [answer()])
    with pytest.raises(ValueError, match="hard links"):
        obtain(tmp_path)
    assert protected.read_bytes() == b"safe"


def test_interrupted_atomic_publication_reopens_the_verified_object(tmp_path, monkeypatch):
    folder = files.directory(tmp_path)
    final, partial = folder / spec().sha256, folder / (spec().sha256 + ".part")
    private_file(partial, CONTENT)
    os.link(partial, final)
    source(monkeypatch, [])
    assert obtain(tmp_path).read_bytes() == CONTENT
    assert final.stat().st_nlink == 1 and not partial.exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://models.example.com/a",
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://models.example.com/x#fragment",
        "https://user:secret@models.example.com/x",
    ],
)
def test_recipe_rejects_insecure_private_or_credentialed_sources(url):
    with pytest.raises(ValueError):
        spec(url)


def test_cancel_after_partial_transfer_keeps_only_unpublished_bytes_for_resume(tmp_path, monkeypatch):
    class Stop(Exception):
        pass

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield CONTENT[:4]
            raise Stop("durable cancellation")

    result = httpx.Response(200, stream=Interrupted(), request=httpx.Request("GET", URL))
    offsets = source(monkeypatch, [result, answer(206, CONTENT[4:], **{"content-range": "bytes 4-7/8"})])
    monkeypatch.setattr(files, "CHUNK", 4)
    with pytest.raises(Stop):
        obtain(tmp_path)
    folder = files.directory(tmp_path)
    assert (folder / (spec().sha256 + ".part")).read_bytes() == CONTENT[:4]
    assert not (folder / spec().sha256).exists()
    assert obtain(tmp_path).read_bytes() == CONTENT
    assert offsets[-1] == (URL, 4)


def test_durable_cancel_interrupts_a_stalled_read_and_closes_stream(tmp_path, monkeypatch):
    class Canceled(Exception):
        pass

    state = {"waiting": False, "closed": False}

    class Stalled(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield CONTENT[:4]
            state["waiting"] = True
            await asyncio.Event().wait()

        async def aclose(self):
            state["closed"] = True

    result = httpx.Response(200, stream=Stalled(), request=httpx.Request("GET", URL))
    source(monkeypatch, [result])
    monkeypatch.setattr(files, "CHUNK", 4)

    def canceled():
        if state["waiting"]:
            raise Canceled("The durable task was stopped")

    with pytest.raises(Canceled):
        obtain(tmp_path, check=canceled)
    assert state["closed"]
    folder = files.directory(tmp_path)
    assert (folder / (spec().sha256 + ".part")).read_bytes() == CONTENT[:4]
    assert not (folder / spec().sha256).exists()


def test_second_worker_cannot_use_a_locked_partial(tmp_path, monkeypatch):
    import fcntl

    folder = files.directory(tmp_path)
    path = folder / (spec().sha256 + ".lock")
    source(monkeypatch, [])
    path.touch(mode=0o600)
    with path.open("w") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(files.DownloadBusy):
            obtain(tmp_path)


def test_http_boundary_pins_dns_and_preserves_authority_without_proxy_or_credentials(tmp_path, monkeypatch):
    calls = []
    original = httpx.AsyncClient

    async def addresses(host):
        assert host == "models.example.com"
        return ["93.184.216.34"]

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(CONTENT))

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(files, "public_addresses", addresses)
    monkeypatch.setattr(files.httpx, "AsyncClient", client)
    assert obtain(tmp_path).read_bytes() == CONTENT
    assert len(calls) == 1
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["Host"] == "models.example.com"
    assert calls[0].extensions["sni_hostname"] == "models.example.com"
    assert "Authorization" not in calls[0].headers and "Cookie" not in calls[0].headers


def test_public_source_cannot_redirect_a_model_download_to_local_services(tmp_path, monkeypatch):
    calls = []
    original = httpx.AsyncClient

    async def addresses(host):
        assert host == "models.example.com"
        return ["93.184.216.34"]

    async def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/admin"})

    def client(**kwargs):
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(files, "public_addresses", addresses)
    monkeypatch.setattr(files.httpx, "AsyncClient", client)
    with pytest.raises(ValueError, match="public HTTPS"):
        obtain(tmp_path)
    assert len(calls) == 1


def test_catalog_candidates_freeze_source_size_hash_license_without_loading_a_runtime():
    from app.setup_models import CANDIDATES, REVISION, candidate

    assert len({item.id for item in CANDIDATES}) == len(CANDIDATES)
    for item in CANDIDATES:
        assert candidate(item.id) is item
        assert item.license == "Apache-2.0" and item.format == "gguf"
        assert item.revision == REVISION and REVISION in item.file.urls[0]
        assert item.file.size_bytes > 1024**3
        assert "main" not in item.file.urls[0]
        assert "installed" not in item.model_dump() and "available" not in item.model_dump()
    assert candidate("arbitrary-user-url-or-path") is None


def test_complete_unpublished_partial_is_verified_before_publication_without_network(tmp_path, monkeypatch):
    folder = files.directory(tmp_path)
    partial = folder / (spec().sha256 + ".part")
    private_file(partial, CONTENT)
    source(monkeypatch, [])
    assert obtain(tmp_path).read_bytes() == CONTENT
    assert not partial.exists()


def test_group_writable_partial_cannot_be_adopted_as_a_shared_model(tmp_path, monkeypatch):
    partial = files.directory(tmp_path) / (spec().sha256 + ".part")
    private_file(partial, CONTENT[:4])
    partial.chmod(0o666)
    source(monkeypatch, [])
    with pytest.raises(ValueError):
        obtain(tmp_path)
    assert partial.read_bytes() == CONTENT[:4]
