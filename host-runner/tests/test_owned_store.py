"""Native metadata finalization cannot select or mutate external file identities."""

import hashlib
import os
import stat

import pytest
from ai_station_runner import owned_store
from ai_station_runner.speech_environment import verified_object


@pytest.fixture
def downloaded(tmp_path):
    raw = b"owned synthetic downloaded bytes"
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "models/store" / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    path.chmod(0o644)
    return tmp_path.resolve(), path, {"sha256": digest, "size_bytes": len(raw)}


def finalize(fixture, **kwargs):
    root, _, item = fixture
    return owned_store.make_download_readonly(root, item["sha256"], item["size_bytes"], **kwargs)


def test_native_write_bits_are_finalized_before_independent_checksum_verification(downloaded):
    root, path, item = downloaded
    before, content = path.stat(), path.read_bytes()
    assert finalize(downloaded) == path
    after = path.stat()
    assert stat.S_IMODE(after.st_mode) == 0o444
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
    assert path.read_bytes() == content
    assert verified_object(root, item, lambda: None) == path


def test_readonly_objects_are_not_rewritten(downloaded, monkeypatch):
    _, path, _ = downloaded
    path.chmod(0o400)
    monkeypatch.setattr(owned_store.os, "fchmod", lambda *a: pytest.fail("Rewrote readonly metadata"))
    assert finalize(downloaded) == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o400


@pytest.mark.parametrize(
    "change", ["symlink", "parent_link", "hardlink", "foreign_owner", "length", "executable"]
)
def test_foreign_alias_or_changed_metadata_is_not_sealed(downloaded, tmp_path, monkeypatch, change):
    root, path, item = downloaded
    if change == "symlink":
        other = tmp_path / "external"
        path.rename(other)
        path.symlink_to(other)
    elif change == "parent_link":
        other = tmp_path / "external"
        path.parent.rename(other)
        path.parent.symlink_to(other, target_is_directory=True)
    elif change == "hardlink":
        os.link(path, tmp_path / "external")
    elif change == "foreign_owner":
        actual = os.geteuid()
        monkeypatch.setattr(owned_store.os, "geteuid", lambda: actual + 1)
    elif change == "length":
        item["size_bytes"] += 1
    else:
        path.chmod(0o755)
    monkeypatch.setattr(owned_store.os, "fchmod", lambda *a: pytest.fail("Changed an unvalidated object"))
    with pytest.raises((ValueError, OSError)):
        finalize(downloaded)


def test_cancellation_before_finalization_keeps_the_source_permissions(downloaded):
    _, path, _ = downloaded
    checks = []

    def check():
        checks.append(True)
        if len(checks) == 2:
            raise InterruptedError("The owned preparation was canceled")

    with pytest.raises(InterruptedError):
        finalize(downloaded, check=check)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_a_replaced_name_is_not_adopted_after_chmod(downloaded, monkeypatch):
    _, path, _ = downloaded
    real = os.fchmod

    def replace(fd, mode):
        real(fd, mode)
        path.unlink()
        path.write_bytes(b"replacement")

    monkeypatch.setattr(owned_store.os, "fchmod", replace)
    with pytest.raises(ValueError, match="changed during"):
        finalize(downloaded)


def test_finalization_is_not_a_checksum_claim(downloaded):
    root, path, item = downloaded
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    finalize(downloaded)
    with pytest.raises(ValueError, match="unexpected hash"):
        verified_object(root, item, lambda: None)
