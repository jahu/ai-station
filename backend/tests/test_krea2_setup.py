"""Pinned companion installation is explicit and independent of inference."""

import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/install-krea2-companions.py"
spec = importlib.util.spec_from_file_location("krea2_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
REAL_CLIENT = httpx.Client


def manifest():
    return {
        "schema_version": 1,
        "name": "test",
        "total_bytes": 5,
        "files": [
            {
                "path": "vae/test.safetensors",
                "source_path": "vae/test.safetensors",
                "repository": "Comfy-Org/Krea-2",
                "revision": "a" * 40,
                "sha256": hashlib.sha256(b"model").hexdigest(),
                "size": 5,
            }
        ],
    }


def mock_download(monkeypatch, payload=b"model"):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        assert not request.headers.get("authorization")
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: REAL_CLIENT(**kw, transport=httpx.MockTransport(respond))
    )
    return calls


def test_manifest_has_only_exact_required_companions():
    actual = setup.load_manifest()
    assert actual["total_bytes"] == 6_410_554_230
    assert len(actual["files"]) == 4
    assert all("lustify" not in i["path"].lower() for i in actual["files"])
    assert all("r64" in i["path"] for i in actual["files"] if i["path"].startswith("loras/"))


def test_plan_is_offline_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("Unexpected network"))
    destination = tmp_path / "missing" / "model"
    assert setup.plan(destination, manifest())["network"] is False
    assert not destination.parent.exists()


def test_download_verify_and_idempotent_rerun(tmp_path, monkeypatch):
    calls = mock_download(monkeypatch)
    destination = tmp_path / "new"
    assert setup.install(destination, manifest())["verified_files"] == 1
    assert len(calls) == 1
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("Unexpected repeated download"))
    assert setup.install(destination, manifest())["verified_files"] == 1
    assert setup.verify(destination, manifest())["network"] is False


def test_interrupted_download_can_resume_without_trusting_partial_bytes(tmp_path, monkeypatch):
    destination = tmp_path / "new"
    mock_download(monkeypatch, b"wrong")
    with pytest.raises(ValueError, match="SHA-256"):
        setup.install(destination, manifest())
    assert not (destination / setup.RECEIPT).exists()
    assert not (destination / manifest()["files"][0]["path"]).exists()
    mock_download(monkeypatch)
    assert setup.install(destination, manifest())["verified_files"] == 1


def test_existing_unknown_directory_and_modified_final_file_are_preserved(tmp_path, monkeypatch):
    destination = tmp_path / "operator"
    destination.mkdir()
    (destination / "keep").write_text("keep")
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("Unexpected network"))
    with pytest.raises(ValueError, match="Existing directory"):
        setup.install(destination, manifest())
    assert (destination / "keep").read_text() == "keep"
    (destination / setup.OWNER).write_text(json.dumps(manifest()))
    (destination / "vae").mkdir()
    target = destination / manifest()["files"][0]["path"]
    target.write_bytes(b"other")
    with pytest.raises(ValueError, match="replace changed"):
        setup.install(destination, manifest())
    assert target.read_bytes() == b"other"


@pytest.mark.parametrize("part", ["root", "directory", "file", "receipt", "partial"])
def test_symlink_boundaries(tmp_path, monkeypatch, part):
    destination = tmp_path / "new"
    outside = tmp_path / "outside"
    outside.mkdir()
    if part == "root":
        destination.symlink_to(outside, target_is_directory=True)
    else:
        destination.mkdir()
        (destination / setup.OWNER).write_text(json.dumps(manifest()))
        if part == "directory":
            (destination / "vae").symlink_to(outside, target_is_directory=True)
        else:
            (destination / "vae").mkdir()
            target = (
                destination
                / {
                    "file": "vae/test.safetensors",
                    "receipt": setup.RECEIPT,
                    "partial": "vae/test.safetensors.partial",
                }[part]
            )
            target.symlink_to(outside / "missing")
    mock_download(monkeypatch)
    with pytest.raises(ValueError, match="symlinks"):
        setup.install(destination, manifest())
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("payload", [b"x", b"too much"])
def test_size_failures_never_publish(tmp_path, monkeypatch, payload):
    mock_download(monkeypatch, payload)
    with pytest.raises(ValueError):
        setup.install(tmp_path / "new", manifest())
    assert not (tmp_path / "new" / setup.RECEIPT).exists()


@pytest.mark.parametrize("path", ["/absolute", "../escape", "vae/../escape", "vae\\escape"])
def test_manifest_paths_are_validated_before_any_write(tmp_path, monkeypatch, path):
    actual = manifest()
    actual["files"][0]["path"] = path
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(actual))
    monkeypatch.setattr(setup, "MANIFEST", source)
    with pytest.raises(ValueError, match="companion"):
        setup.load_manifest()


@pytest.mark.parametrize(
    "url", ["http://huggingface.co/f", "https://localhost/f", "https://u@huggingface.co/f"]
)
def test_redirects_cannot_leak_credentials_or_use_local_services(url):
    with pytest.raises(ValueError, match="public model"):
        setup.public_url(url)
