import hashlib
import io
import json
import os
import shutil
import subprocess
import urllib.request

import pytest
import windows_gpu_bundle as bundle


@pytest.fixture
def publisher(monkeypatch):
    data = b"synthetic package fixture; never installed"
    monkeypatch.setattr(
        bundle, "PACKAGES", (("nvidia-fixture", len(data), hashlib.sha256(data).hexdigest()),)
    )
    calls = []

    class Source:
        def open(self, url, timeout):
            calls.append((url, timeout))
            return io.BytesIO(data)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Source())
    return data, calls


def test_fixed_bundle_records_verified_inputs_and_never_installs(tmp_path, publisher):
    data, calls = publisher
    output = tmp_path / "inputs"
    metadata = bundle.prepare(output)
    assert bundle.verify(output) == metadata
    assert len(list(output.iterdir())) == 2
    assert calls == [(bundle.REPOSITORY + f"nvidia-fixture_{bundle.VERSION}_amd64.deb", 30)]
    assert (output / metadata["packages"][0]["filename"]).read_bytes() == data
    assert not list(tmp_path.glob(".windows-gpu-*"))


def test_cached_inputs_are_reverified_and_copied_without_network(tmp_path, publisher, monkeypatch):
    cache = tmp_path / "cache"
    bundle.prepare(cache)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: None)
    output = tmp_path / "other"
    assert bundle.prepare(output, cache=cache) == bundle.verify(cache)
    package = bundle.metadata()["packages"][0]["filename"]
    assert (output / package).stat().st_ino != (cache / package).stat().st_ino


@pytest.mark.parametrize("failure", ["truncated", "oversized", "changed", "network"])
def test_invalid_download_has_no_published_bundle_or_leftovers(tmp_path, publisher, monkeypatch, failure):
    data, _ = publisher

    class Source:
        def open(self, url, timeout):
            if failure == "network":
                raise OSError("fixture offline")
            return io.BytesIO(
                data[:-1]
                if failure == "truncated"
                else data + b"!"
                if failure == "oversized"
                else b"x" * len(data)
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Source())
    before = set(tmp_path.iterdir())
    with pytest.raises((ValueError, OSError)):
        bundle.prepare(tmp_path / "inputs")
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("damage", ["hash", "length", "receipt", "extra", "symlink", "hardlink", "write"])
def test_modified_inputs_are_rejected_before_offline_reuse(tmp_path, publisher, damage):
    root = tmp_path / "inputs"
    bundle.prepare(root)
    package = root / bundle.metadata()["packages"][0]["filename"]
    if damage == "hash":
        package.write_bytes(b"x" * package.stat().st_size)
    elif damage == "length":
        package.write_bytes(b"short")
    elif damage == "receipt":
        p = root / "bundle.json"
        value = json.loads(p.read_bytes())
        value["packages"][0]["version"] = "another version"
        p.write_text(json.dumps(value))
    elif damage == "extra":
        (root / "unexpected.deb").touch()
    elif damage == "symlink":
        outside = tmp_path / "outside"
        package.rename(outside)
        package.symlink_to(outside)
    elif damage == "hardlink":
        os.link(package, tmp_path / "outside")
    else:
        package.chmod(0o664)
    with pytest.raises(ValueError):
        bundle.prepare(tmp_path / "other", cache=root)
    assert not (tmp_path / "other").exists()


@pytest.mark.parametrize("kind", ["existing", "symlink", "parent_link"])
def test_existing_output_and_symlink_parent_are_preserved(tmp_path, publisher, kind):
    existing = tmp_path / "saved"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("user data")
    output = existing
    if kind != "existing":
        link = tmp_path / "link"
        link.symlink_to(existing, target_is_directory=True)
        output = link if kind == "symlink" else link / "new"
    with pytest.raises(ValueError):
        bundle.prepare(output)
    assert sentinel.read_text() == "user data"


def test_publisher_redirects_are_not_followed():
    with pytest.raises(ValueError, match="redirected"):
        bundle.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://127.0.0.1/private")


def test_pinned_packages_are_exact_toolkit_inputs_without_display_drivers():
    assert {row["name"] for row in bundle.metadata()["packages"]} == {
        "nvidia-container-toolkit",
        "nvidia-container-toolkit-base",
        "libnvidia-container1",
        "libnvidia-container-tools",
    }
    assert sum(row["size_bytes"] for row in bundle.metadata()["packages"]) == 8751700
    assert all(row["version"] == "1.20.1-1" for row in bundle.metadata()["packages"])


@pytest.mark.skipif(not shutil.which("dpkg-deb"), reason="Debian package inspection requires dpkg-deb")
@pytest.mark.parametrize("windows_gpu", [False, True])
def test_os_package_only_declares_the_verified_opt_in_gpu_bundle(tmp_path, publisher, windows_gpu):
    import build_linux_package as builder

    root = tmp_path / "desktop"
    root.mkdir()
    (root / "station").write_text("synthetic desktop fixture; never launched")
    metadata = {"source_epoch": 1793520000, "bundle_id": "a" * 64}
    if windows_gpu:
        metadata["windows_gpu_recipe"] = bundle.RECIPE
        bundle.prepare(root / "windows-gpu")
    package = builder.deb(root, metadata)
    value = subprocess.check_output(
        ["dpkg-deb", "--field", str(package), "X-AI-Station-WSL-GPU-Recipe"], text=True
    ).strip()
    assert value == (bundle.RECIPE if windows_gpu else "")
    members = subprocess.check_output(["dpkg-deb", "--contents", str(package)], text=True)
    assert ("windows-gpu/bundle.json" in members) is windows_gpu
    scripts = subprocess.check_output(["dpkg-deb", "--ctrl-tarfile", str(package)])
    # The package carries offline inputs, never an automatic installation hook.
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(scripts)) as archive:
        assert not any(
            m.name.rsplit("/", 1)[-1] in {"preinst", "postinst", "prerm", "postrm"} for m in archive
        )


def test_package_rejects_a_gpu_recipe_without_its_exact_verified_inputs(tmp_path, publisher):
    import build_linux_package as builder

    root = tmp_path / "desktop"
    root.mkdir()
    value = {"source_epoch": 1793520000, "bundle_id": "a" * 64, "windows_gpu_recipe": bundle.RECIPE}
    bundle.prepare(root / "windows-gpu")
    package = root / "windows-gpu" / bundle.metadata()["packages"][0]["filename"]
    package.write_bytes(b"unreviewed")
    with pytest.raises(ValueError):
        builder.deb(root, value)
    assert not root.with_suffix(".deb").exists()


def test_a_cache_cannot_implicitly_enable_windows_gpu_packaging(tmp_path):
    import build_linux_package as builder

    with pytest.raises(ValueError, match="explicit"):
        builder.build(tmp_path / "package", gpu_cache=tmp_path / "cache")
