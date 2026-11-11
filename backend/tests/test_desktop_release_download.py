import copy
import hashlib
import io
import json
import urllib.request

import desktop_release_download as module
import pytest
from ai_station_runner.station_release_metadata import API, admit_release
from test_station_updates import release

CONTENT = b"verified official installer fixture"


def snapshot():
    raw = release()
    raw["assets"][0]["size"] = len(CONTENT)
    raw["assets"][0]["digest"] = "sha256:" + hashlib.sha256(CONTENT).hexdigest()
    return admit_release(raw)


class Response(io.BytesIO):
    status = 200

    def __init__(self, content, url, headers=None):
        super().__init__(content)
        self.url, self.headers = url, headers or {}

    def geturl(self):
        return self.url


def fixture(monkeypatch, tmp_path, content=CONTENT, changed=None, headers=None):
    tmp_path.chmod(0o700)
    value = snapshot()
    calls = []
    monkeypatch.setattr(module, "official_release", lambda identity, check: copy.deepcopy(changed or value))

    def opener(url, **kwargs):
        calls.append(url)
        return Response(content, url, headers)

    monkeypatch.setattr(module, "open_official", opener)

    def obtain(**kwargs):
        return module.download(
            tmp_path, value["release_id"], value["fingerprint"], "0.4.0", "linux-amd64", **kwargs
        )

    return obtain, calls


def test_verified_package_is_private_and_reused_only_after_rechecking_publisher(monkeypatch, tmp_path):
    obtain, calls = fixture(monkeypatch, tmp_path)
    path, value = obtain()
    assert path.read_bytes() == CONTENT
    assert path.stat().st_mode & 0o777 == 0o400
    assert value == snapshot()
    assert calls[0].startswith(f"{API}/releases/assets/456?")
    assert obtain()[0] == path
    assert len(calls) == 1
    assert not list(path.parent.glob("*.part"))


@pytest.mark.parametrize(
    "content,headers",
    [
        (b"truncated", {}),
        (b"x" * 100, {}),
        (b"X" * len(CONTENT), {}),
        (CONTENT, {"Content-Length": "999"}),
        (CONTENT, {"Content-Encoding": "gzip"}),
    ],
)
def test_unverified_transfers_are_removed_and_never_published(monkeypatch, tmp_path, content, headers):
    obtain, _ = fixture(monkeypatch, tmp_path, content, headers=headers)
    with pytest.raises(ValueError):
        obtain()
    assert list((tmp_path / "update-downloads").iterdir()) == []


def test_publisher_change_is_rejected_before_download(monkeypatch, tmp_path):
    changed = snapshot() | {"fingerprint": "b" * 64}
    obtain, calls = fixture(monkeypatch, tmp_path, changed=changed)
    with pytest.raises(ValueError, match="changed since"):
        obtain()
    assert not calls


def test_cancellation_cleans_partial_transfer(monkeypatch, tmp_path):
    obtain, _ = fixture(monkeypatch, tmp_path)

    def canceled():
        raise InterruptedError("Canceled by operator")

    with pytest.raises(InterruptedError):
        obtain(check=canceled)
    assert list((tmp_path / "update-downloads").iterdir()) == []


def test_changed_cache_and_symlinks_are_not_reused(monkeypatch, tmp_path):
    obtain, calls = fixture(monkeypatch, tmp_path)
    path, _ = obtain()
    path.chmod(0o600)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="saved update package changed"):
        obtain()
    path.unlink()
    path.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="owned regular file"):
        obtain()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "target",
    [
        "http://github.com/file",
        "https://localhost/file",
        "https://github.com.evil.example/file",
        "https://user:password@github.com/file",
        "https://github.com:444/file",
        "https://release-assets.githubusercontent.com/file#fragment",
    ],
)
def test_redirects_cannot_escape_official_https_hosts(target):
    request = urllib.request.Request(f"{API}/releases/assets/456")
    with pytest.raises(ValueError, match="unexpected source"):
        module.ReleaseRedirect().redirect_request(request, None, 302, "", {}, target)


def test_native_metadata_rechecks_official_id_and_duplicate_fields(monkeypatch):
    raw = release()
    monkeypatch.setattr(module, "open_official", lambda url: Response(json.dumps(raw).encode(), url))
    assert module.official_release(123)["release_id"] == 123
    with pytest.raises(ValueError, match="identity changed"):
        module.official_release(124)
    monkeypatch.setattr(module, "open_official", lambda url: Response(b'{"id":1,"id":2}', url))
    with pytest.raises(ValueError, match="Duplicate"):
        module.official_release(123)
