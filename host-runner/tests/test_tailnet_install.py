"""Pinned dependency installation stays private, bounded and non-destructive."""

import hashlib
import io
import os
import tarfile

import httpx
import pytest
from ai_station_runner import tailnet_install as mod


def archive(*, kind="valid"):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as out:
        for name in ("tailscale", "tailscaled"):
            item = tarfile.TarInfo(f"tailscale_{mod.VERSION}_amd64/{name}")
            raw = b"fixture executable " + name.encode()
            item.size = len(raw)
            item.mode = 0o755
            if kind == "symlink" and name == "tailscale":
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
            if kind == "suid" and name == "tailscale":
                item.mode = 0o4755
            if kind == "empty" and name == "tailscale":
                raw = b""
                item.size = 0
            out.addfile(item, io.BytesIO(raw))
            if kind == "duplicate" and name == "tailscale":
                out.addfile(item, io.BytesIO(raw))
    return data.getvalue()


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mod.platform, "machine", lambda: "x86_64")
    calls = []

    def client(data, *, status=200):
        monkeypatch.setitem(mod.ARCHIVES, "amd64", hashlib.sha256(data).hexdigest())

        def respond(request):
            assert str(request.url) == f"https://pkgs.tailscale.com/stable/tailscale_{mod.VERSION}_amd64.tgz"
            calls.append(str(request.url))
            return httpx.Response(
                status, content=data, headers={"location": "https://example.invalid/redirect"}
            )

        return httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)

    return client, calls


def test_installs_only_verified_binaries_and_reuses_without_network(tmp_path, source):
    client, calls = source
    with client(archive()) as web:
        path = mod.install(tmp_path / "owned", client=web)
        assert {p.name for p in path.iterdir()} == {"install.json", "tailscale", "tailscaled"}
        assert mod.verified_install(path, "amd64")["version"] == mod.VERSION
        assert mod.install(tmp_path / "owned", client=web) == path and len(calls) == 1
        assert path.stat().st_mode & 0o777 == 0o700
        assert (path / "install.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ["symlink", "suid", "empty", "duplicate"])
def test_unsafe_or_missing_binary_is_never_published(tmp_path, source, kind):
    client, _ = source
    with client(archive(kind=kind)) as web, pytest.raises(ValueError):
        mod.install(tmp_path / "owned", client=web)
    assert not list((tmp_path / "owned").glob("tailscale-*"))
    assert not list((tmp_path / "owned").glob(".install-*"))


def test_checksum_failure_keeps_existing_files_and_cleans_only_own_stage(tmp_path, source, monkeypatch):
    client, _ = source
    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    original = root / "keep.txt"
    original.write_text("preserved")
    with client(archive()) as web:
        monkeypatch.setitem(mod.ARCHIVES, "amd64", "0" * 64)
        with pytest.raises(ValueError, match="SHA-256"):
            mod.install(root, client=web)
    assert original.read_text() == "preserved" and {p.name for p in root.iterdir()} == {
        "keep.txt",
        "install.lock",
    }


@pytest.mark.parametrize("change", ["bytes", "receipt", "symlink", "hardlink", "permissions"])
def test_existing_installation_is_not_overwritten_when_changed(tmp_path, source, change):
    client, calls = source
    with client(archive()) as web:
        path = mod.install(tmp_path / "owned", client=web)
        binary = path / "tailscale"
        if change == "bytes":
            binary.write_bytes(b"changed")
        elif change == "receipt":
            (path / "install.json").write_text("{}")
        elif change == "symlink":
            binary.unlink()
            binary.symlink_to("/etc/passwd")
        elif change == "hardlink":
            os.link(binary, tmp_path / "alias")
        else:
            binary.chmod(0o755)
        with pytest.raises((ValueError, OSError)):
            mod.install(tmp_path / "owned", client=web)
        assert len(calls) == 1


def test_diagnostics_do_not_create_missing_installation(tmp_path):
    path = tmp_path / "absent"
    with pytest.raises(FileNotFoundError):
        mod.verified_install(path, "amd64")
    assert not path.exists()


def test_cancel_before_download_has_no_network_side_effect(tmp_path, source):
    client, calls = source
    with client(archive()) as web, pytest.raises(InterruptedError):
        mod.install(tmp_path / "owned", client=web, canceled=lambda: True)
    assert not calls and not list((tmp_path / "owned").glob("tailscale-*"))


def test_redirect_is_not_followed_even_with_a_redirecting_client(tmp_path, source):
    client, calls = source
    with client(archive(), status=302) as web, pytest.raises(httpx.HTTPStatusError):
        mod.install(tmp_path / "owned", client=web)
    assert len(calls) == 1


def test_cache_symlink_and_broad_permissions_are_rejected(tmp_path):
    root = tmp_path / "outside"
    root.mkdir(mode=0o700)
    link = tmp_path / "alias"
    link.symlink_to(root)
    with pytest.raises(ValueError):
        mod.private_directory(link)
    root.chmod(0o755)
    with pytest.raises(ValueError):
        mod.private_directory(root)
