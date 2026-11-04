"""Fixed music assembly and managed links with tiny objects; no GPU/downloads."""

import hashlib
import json
import os
from uuid import uuid4

import pytest
from ai_station_runner import music_environment as environment
from ai_station_runner import music_protocol


def object_file(root, filename, content, kind):
    digest = hashlib.sha256(content).hexdigest()
    store = root / "models/store"
    store.mkdir(parents=True, exist_ok=True)
    path = store / digest
    path.write_bytes(content)
    path.chmod(0o444)
    return dict(filename=filename, kind=kind, sha256=digest, size_bytes=len(content))


def test_builtin_recipe_keeps_the_qualified_external_music_identity():
    value = environment.recipe()
    assert value["profile"] == environment.PROFILE and len(value["inputs"]) == 92
    assert value["python"] == "3.12" and value["glibc_minimum"] == "2.28"
    assert environment.fingerprint(value["model_manifest"]) == music_protocol.MANIFEST_SHA256
    models = [v for v in value["inputs"] if v["kind"] == "model"]
    assert len(models) == 16 and sum(v["size_bytes"] for v in models) == 6336680772
    assert all(value["model_revision"] in v["url"] for v in models)
    assert all(v["url"].startswith("https://") and len(v["sha256"]) == 64 for v in value["inputs"])
    versions = {v["name"]: v["version"] for v in value["inputs"] if v["kind"] == "wheel"}
    assert versions["torch"] == versions["torchaudio"] == "2.10.0+cu128"


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    items = [
        object_file(tmp_path, "python.tar.gz", b"python", "python"),
        object_file(tmp_path, "sdk.tar.gz", b"sdk", "sdk"),
        object_file(tmp_path, "fixture-1.0-py3-none-any.whl", b"wheel", "wheel"),
        object_file(tmp_path, "weights/model.bin", b"frozen weights", "model"),
    ]
    items[2].update(name="fixture", version="1.0")
    manifest = {
        "files": [
            {"path": items[3]["filename"], "size": items[3]["size_bytes"], "sha256": items[3]["sha256"]}
        ]
    }
    monkeypatch.setattr(music_protocol, "MANIFEST_SHA256", environment.fingerprint(manifest))
    recipe = {"profile": environment.PROFILE, "inputs": items, "model_manifest": manifest}
    monkeypatch.setattr(environment, "recipe", lambda: recipe)
    commands = []

    def unpack_python(_object, folder, check):
        folder.joinpath("python/bin").mkdir(parents=True)
        binary = folder / "python/bin/python3.12"
        binary.write_bytes(b"fake interpreter; never executed")
        return binary

    def unpack_sdk(_object, folder, check):
        source = folder / "fixed-sdk"
        (source / "acestep").mkdir(parents=True)
        (source / "acestep/__init__.py").write_text("# fixed SDK")
        digest = hashlib.sha256()
        name, content = b"__init__.py", b"# fixed SDK"
        for part in (name, content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
        monkeypatch.setattr(music_protocol, "SOURCE_SHA256", digest.hexdigest())
        return source

    def command(argv, *, folder, check):
        check()
        commands.append(argv)
        if "venv" in argv:
            folder.joinpath("venv/bin").mkdir(parents=True)
            (folder / "venv/bin/python").symlink_to(folder / "python/bin/python3.12")

    monkeypatch.setattr(environment, "unpack_python", unpack_python)
    monkeypatch.setattr(environment, "unpack_tar", unpack_sdk)
    monkeypatch.setattr(environment, "command", command)
    return tmp_path, items, commands


def test_preparation_uses_fixed_offline_wheels_and_closes_model_links(fixture):
    root, items, commands = fixture
    identity = str(uuid4())
    result = environment.prepare(root, identity)
    folder = root / result["relative_path"]
    assert result["environment_prepared"] and result["music_inference_tested"] is False
    assert json.loads((folder / "ready.json").read_text()) == result
    assert (folder / "models/weights/model.bin").resolve() == root / "models/store" / items[3]["sha256"]
    assert (root / "models/store" / items[3]["sha256"]).stat().st_nlink == 1
    install = next(argv for argv in commands if "install" in argv)
    assert {"--no-index", "--no-deps", "--require-hashes", "--only-binary"} <= set(install)
    assert "fixture==1.0 --hash=sha256:" in (folder / "requirements.lock").read_text()
    with pytest.raises(ValueError, match="Inspect the existing"):
        environment.prepare(root, identity)


def test_incomplete_or_changed_inputs_never_execute_or_publish_readiness(fixture):
    root, items, commands = fixture
    target = root / "models/store" / items[-1]["sha256"]
    target.chmod(0o600)
    with pytest.raises(ValueError, match="immutable"):
        environment.prepare(root, str(uuid4()))
    assert commands == [] and not list(root.rglob("ready.json"))


def test_stop_is_checked_before_executing_unpacked_dependencies(fixture):
    root, _, commands = fixture

    def stop():
        raise InterruptedError("Stopped")

    with pytest.raises(InterruptedError):
        environment.prepare(root, str(uuid4()), check=stop)
    assert commands == [] and not list(root.rglob("ready.json"))


@pytest.mark.parametrize(
    "change", ["symlink", "parent_symlink", "hardlink", "writable", "fifo", "large", "array"]
)
def test_environment_metadata_rejects_unsafe_or_unbounded_files(tmp_path, change):
    folder = tmp_path / "owned"
    folder.mkdir()
    receipt = folder / "active.json"
    receipt.write_text('{"operation_id":"owned"}')
    receipt.chmod(0o600)
    assert environment.read_json(receipt) == {"operation_id": "owned"}
    if change == "symlink":
        target = folder / "other.json"
        receipt.rename(target)
        receipt.symlink_to(target)
    elif change == "parent_symlink":
        folder.rename(tmp_path / "moved")
        folder.symlink_to(tmp_path / "moved")
    elif change == "hardlink":
        os.link(receipt, tmp_path / "alias")
    elif change == "writable":
        receipt.chmod(0o666)
    elif change == "fifo":
        receipt.unlink()
        os.mkfifo(receipt)
    elif change == "large":
        receipt.write_text('{"payload":"' + "x" * 32768 + '"}')
    else:
        receipt.write_text("[]")
    with pytest.raises(ValueError):
        environment.read_json(receipt)


@pytest.mark.parametrize(
    "change", ["outside", "wrong_hash_target", "parent_symlink", "writable", "hardlink", "traversal"]
)
def test_managed_model_view_cannot_relax_external_file_boundaries(fixture, change):
    root, items, _ = fixture
    result = environment.prepare(root, str(uuid4()))
    model_root = root / result["relative_path"] / "models"
    view = model_root / items[-1]["filename"]
    target = view.resolve()
    if change in {"outside", "wrong_hash_target"}:
        other = root / ("outside-model" if change == "outside" else "models/store/" + "a" * 64)
        other.write_bytes(b"frozen weights")
        other.chmod(0o444)
        view.unlink()
        view.symlink_to(other)
    elif change == "parent_symlink":
        (model_root / "weights").rename(model_root / "moved")
        (model_root / "weights").symlink_to(model_root / "moved")
    elif change == "writable":
        target.chmod(0o600)
    elif change == "hardlink":
        os.link(target, root / "extra-link")
    else:
        item = {"path": "../escape", "sha256": items[-1]["sha256"], "size": items[-1]["size_bytes"]}
        with pytest.raises((ValueError, FileNotFoundError)):
            music_protocol.model_file(model_root, item, immutable_root=root / "models/store")
        return
    with pytest.raises(ValueError):
        music_protocol.model_manifest(model_root, immutable_root=root / "models/store")
    # Legacy external paths never accept the managed symlink exception.
    with pytest.raises(ValueError, match="symlink"):
        music_protocol.model_manifest(model_root)
