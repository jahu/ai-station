"""Reuse advice never reads weights, invents compatibility or authorizes execution."""

import hashlib
import os
from copy import deepcopy

import pytest
from app.config import get_settings
from app.model_cache_advice import apply
from app.models import ModelFile


def recorded(session):
    raw = b"synthetic previously verified model"
    digest = hashlib.sha256(raw).hexdigest()
    root = get_settings().data_dir
    folder = root / "models/store"
    folder.mkdir(parents=True)
    path = folder / digest
    path.write_bytes(raw)
    path.chmod(0o444)
    session.add(
        ModelFile(
            sha256=digest,
            relative_path="models/store/" + digest,
            filename="model.gguf",
            size_bytes=len(raw),
            mtime=path.stat().st_mtime,
            format="gguf",
            category="llm",
            availability="present",
            root_label="AI Station storage",
        )
    )
    session.commit()
    report = {
        "files": [
            {
                "filename": "model.gguf",
                "sha256": digest,
                "size_bytes": len(raw),
                "identity_available": True,
                "assessment": {
                    "reason": "Unknown runtime profile",
                    "hardware_status": "unknown",
                    "runtime_status": "needs_compatible_recipe",
                    "disk": {
                        "file_bytes": len(raw),
                        "free_bytes": 100,
                        "headroom_bytes": 100,
                        "status": "insufficient",
                    },
                },
            }
        ]
    }
    return path, raw, report


@pytest.mark.parametrize("allowance", [0, 500])
def test_cache_reuse_changes_only_additional_disk_cost_not_unsupported_runtime(
    session, monkeypatch, allowance
):
    from pathlib import Path

    path, raw, report = recorded(session)

    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata-only cache advice must not read model payloads")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    report["files"][0]["assessment"]["disk"].update(
        install_bytes_upper_bound=len(raw) + allowance, free_bytes=100 + allowance
    )
    before = deepcopy(report["files"][0]["assessment"])
    apply(session, report, lambda: None)
    result = report["files"][0]["assessment"]
    assert result["disk"]["reusable_model_bytes"] == len(raw)
    assert result["disk"]["additional_bytes_upper_bound"] == allowance
    assert result["disk"]["model_download_bytes_estimate"] == 0
    assert result["disk"]["status"] == "file_fits"
    assert result["hardware_status"] == before["hardware_status"] == "unknown"
    assert result["runtime_status"] == before["runtime_status"] == "needs_compatible_recipe"
    from app.hub_comparisons import suitability

    report["files"][0]["assessment"]["profiles"] = []
    _, summary = suitability(report, set(), 32768)
    assert summary["download_bytes_estimate"] == 0
    assert summary["additional_installation_bytes_upper_bound"] == allowance
    assert summary["suitability"] == "unsupported"


@pytest.mark.parametrize("change", ["missing", "writable", "symlink", "hardlink", "mtime", "parent-symlink"])
def test_changed_or_unsafe_cache_observations_cannot_discount_space(session, change):
    path, raw, report = recorded(session)
    if change == "missing":
        path.unlink()
    elif change == "writable":
        path.chmod(0o644)
    elif change == "symlink":
        other = path.with_name("other")
        path.rename(other)
        path.symlink_to(other)
    elif change == "hardlink":
        os.link(path, path.with_name("other"))
    elif change == "mtime":
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 1))
    else:
        folder = path.parent
        other = folder.with_name("moved-store")
        folder.rename(other)
        folder.symlink_to(other, target_is_directory=True)
    apply(session, report, lambda: None)
    assert report["files"][0]["assessment"]["disk"]["status"] == "insufficient"
    assert report["files"][0]["assessment"]["disk"]["reusable_model_bytes"] == 0


def test_matching_stat_advice_does_not_replace_installation_hash_authority(session):
    from app.model_download_files import FileSpec, VerificationFailed, verify

    path, raw, report = recorded(session)
    info = path.stat()
    path.chmod(0o644)
    path.write_bytes(b"X" * len(raw))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    path.chmod(0o444)
    apply(session, report, lambda: None)
    assert report["files"][0]["assessment"]["disk"]["model_weights_available"]
    spec = FileSpec(sha256=path.name, size_bytes=len(raw), urls=("https://models.example.com/fixture.gguf",))
    with pytest.raises(VerificationFailed):
        verify(path, spec, lambda: None)
