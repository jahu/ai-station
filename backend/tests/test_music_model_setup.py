"""Music setup must never silently fetch weights or modify an existing model."""

import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/install-music-model.py"
spec = importlib.util.spec_from_file_location("music_model_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def small_manifest():
    return {
        "schema_version": 1,
        "repository": "ACE-Step/Ace-Step1.5",
        "revision": "a" * 40,
        "code_revision": "b" * 40,
        "total_bytes": 5,
        "files": [{"path": "vae/test.bin", "size": 5, "sha256": hashlib.sha256(b"music").hexdigest()}],
    }


def test_real_manifest_pins_all_files_and_exact_bytes():
    manifest = setup.load_manifest()
    assert manifest["total_bytes"] == 6_336_680_772
    assert len(manifest["files"]) == 16
    assert len({item["sha256"] for item in manifest["files"]}) == 16


def test_default_plan_is_offline_and_does_not_create_directories(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("An offline plan attempted networking")

    monkeypatch.setattr(httpx, "Client", forbidden)
    destination = tmp_path / "missing-parent" / "new-model"
    plan = setup.plan(destination, small_manifest())
    assert plan["network"] is False
    assert plan["runtime_installed"] is False
    assert plan["music_generation_verified"] is False
    assert plan["destination_exists"] is False
    assert not destination.parent.exists()
    assert "/resolve/" + "a" * 40 + "/vae/test.bin" in plan["files"][0]["url"]


@pytest.mark.parametrize("target", ["model", "parent/model"])
def test_destination_symlinks_are_rejected(tmp_path, target):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / target.split("/")[0]).symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        setup.plan(tmp_path / target, small_manifest())


def test_existing_destination_is_not_overwritten_or_removed(tmp_path, monkeypatch):
    destination = tmp_path / "operator-model"
    destination.mkdir()
    saved = destination / "keep.txt"
    saved.write_text("operator data")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Unexpected download"))
    with pytest.raises(ValueError, match="already exists"):
        setup.install(destination, small_manifest())
    assert saved.read_text() == "operator data"


def test_explicit_install_verifies_download_and_receipt(tmp_path, monkeypatch):
    calls = []
    real_client = httpx.Client

    def respond(request):
        calls.append(str(request.url))
        assert request.headers.get("authorization") is None
        return httpx.Response(200, content=b"music")

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "Client", client)
    destination = tmp_path / "new-model"
    manifest = small_manifest()
    assert setup.install(destination, manifest)["verified_files"] == 1
    assert json.loads((destination / setup.RECEIPT).read_text()) == manifest
    assert (destination / "vae/test.bin").read_bytes() == b"music"
    assert len(calls) == 1
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Offline verify used network"))
    assert setup.verify(destination, manifest)["network"] is False
    (destination / "vae/test.bin").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="SHA-256"):
        setup.verify(destination, manifest)


@pytest.mark.parametrize("payload", [b"bad", b"wrong", b"too much"])
def test_failed_download_cannot_publish_a_ready_receipt(tmp_path, monkeypatch, payload):
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
        ),
    )
    destination = tmp_path / "incomplete-model"
    with pytest.raises(ValueError):
        setup.install(destination, small_manifest())
    assert destination.exists()
    assert not (destination / setup.RECEIPT).exists()
    assert not (destination / "vae/test.bin").exists()
    with pytest.raises(ValueError, match="receipt"):
        setup.verify(destination, small_manifest())
    with pytest.raises(ValueError, match="already exists"):
        setup.install(destination, small_manifest())


@pytest.mark.parametrize(
    "url",
    [
        "http://huggingface.co/file",
        "https://huggingface.co.evil.test/file",
        "https://localhost/file",
        "https://127.0.0.1/file",
        "https://huggingface.co@evil.test/file",
        "https://secret@huggingface.co/file",
        "https://huggingface.co:444/file",
    ],
)
def test_download_redirects_reject_credentials_and_other_services(url):
    with pytest.raises(ValueError, match="outside"):
        setup.public_download_url(url)


def test_download_accepts_public_model_cdn_and_bounds_redirects(tmp_path):
    target = tmp_path / "file"
    seen = []

    def respond(request):
        seen.append(str(request.url))
        if request.url.host == "huggingface.co":
            return httpx.Response(302, headers={"location": "https://cas-bridge.xethub.hf.co/file"})
        return httpx.Response(200, content=b"music")

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False) as client:
        setup.download_file(client, "https://huggingface.co/file", target, small_manifest()["files"][0])
    assert target.read_bytes() == b"music"
    assert len(seen) == 2
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "https://huggingface.co/loop"})
        ),
        follow_redirects=False,
    ) as client:
        with pytest.raises(ValueError, match="redirect limit"):
            setup.download_file(
                client, "https://huggingface.co/loop", tmp_path / "loop", small_manifest()["files"][0]
            )


def test_offline_verification_rejects_symlinked_file(tmp_path):
    manifest = small_manifest()
    destination = tmp_path / "model"
    (destination / "vae").mkdir(parents=True)
    (destination / setup.RECEIPT).write_text(json.dumps(manifest))
    outside = tmp_path / "outside"
    outside.write_bytes(b"music")
    (destination / "vae/test.bin").symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        setup.verify(destination, manifest)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "vae/../../escape", "vae\\escape", "vae/file"])
def test_modified_manifest_is_rejected(tmp_path, monkeypatch, path):
    manifest = small_manifest()
    manifest["files"][0]["path"] = path
    manifest["total_bytes"] = 100  # including an otherwise valid path
    file = tmp_path / "manifest.json"
    file.write_text(json.dumps(manifest))
    monkeypatch.setattr(setup, "MANIFEST", file)
    with pytest.raises(ValueError):
        setup.load_manifest()
