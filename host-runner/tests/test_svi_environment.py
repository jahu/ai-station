"""Owned recurrent environment contract with synthetic data and fake commands."""

import hashlib
import json
import os
from uuid import uuid4

import pytest
from ai_station_runner import svi_environment as environment


def test_svi_recipe_keeps_dependencies_and_excludes_unused_five_billion_weights():
    frozen = environment.recipe()
    assert not environment.QUALIFIED
    models = [row for row in frozen["inputs"] if row["kind"] == "model"]
    assert {row["role"] for row in models} == environment.ROLES
    assert all("ti2v_5B" not in row["filename"] and "wan2.2_vae" not in row["filename"] for row in models)
    versions = {row["name"]: row["version"] for row in frozen["inputs"] if row["kind"] == "wheel"}
    assert len(versions) == 98 and versions["gguf"] == "0.19.0"
    assert versions["torch"] == versions["torchaudio"] == "2.11.0"


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    names = [("python.tar.gz", "python", None), ("fixture-1.0-py3-none-any.whl", "wheel", None)]
    names += [(name + ".tar.gz", "sdk", name) for name in ("ComfyUI", "ComfyUI-GGUF")]
    names += [
        (name + (".gguf" if "noise" in name else ".safetensors"), "model", name)
        for name in sorted(environment.ROLES)
    ]
    items = []
    for filename, kind, role in names:
        data = filename.encode()
        sha = hashlib.sha256(data).hexdigest()
        (store / sha).write_bytes(data)
        (store / sha).chmod(0o444)
        item = {"filename": filename, "kind": kind, "sha256": sha, "size_bytes": len(data)}
        if kind == "model":
            item["role"] = role
        elif kind == "sdk":
            item["name"] = role
        elif kind == "wheel":
            item.update(name="fixture", version="1.0")
        items.append(item)
    content = b"# fixed fake SDK; never imported"
    source_hash = environment.fingerprint(
        [{"path": "nodes.py", "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}]
    )
    frozen = {
        "profile": environment.PROFILE,
        "inputs": items,
        "source_sha256": source_hash,
        "gguf_source_sha256": source_hash,
    }
    monkeypatch.setattr(environment, "recipe", lambda: frozen)

    def unpack_python(_object, folder, check):
        path = folder / "python/bin/python3.12"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"fake Python; never executed")
        path.chmod(0o700)
        return path

    def unpack_source(_object, folder, check):
        source = folder / ("fixture-" + _object.name)
        source.mkdir()
        (source / "nodes.py").write_bytes(content)
        return source

    calls = []

    def command(argv, *, folder, check):
        check()
        calls.append(argv)
        if "venv" in argv:
            path = folder / "venv/bin/python"
            path.parent.mkdir(parents=True)
            path.symlink_to(folder / "python/bin/python3.12")

    monkeypatch.setattr(environment, "unpack_python", unpack_python)
    monkeypatch.setattr(environment, "unpack_tar", unpack_source)
    monkeypatch.setattr(environment, "command", command)
    return tmp_path, frozen, calls


def prepare(fixture):
    root, frozen, calls = fixture
    ready = environment.prepare(root, str(uuid4()))
    observed = {key: ready[key] for key in ("profile", "manifest_sha256", "operation_id")}
    return root, ready, observed


def test_separate_engine_resolves_only_after_complete_offline_assembly(fixture):
    root, ready, observed = prepare(fixture)
    selected = environment.resolve(root, observed)
    assert selected["managed"] and ready["video_inference_tested"] is False
    assert selected["video_python"].resolve() == selected["environment"] / "python/bin/python3.12"
    assert selected["gguf_dir"] != selected["comfy_dir"]
    assert environment.ROLES <= selected.keys()
    calls = fixture[2]
    install = next(argv for argv in calls if "install" in argv)
    assert {"--no-index", "--no-deps", "--require-hashes", "--only-binary"} <= set(install)
    assert any("svi_environment_probe.py" in item for item in calls[-1])
    assert not (root / "runtime/video-environments").exists()
    with pytest.raises(ValueError, match="Inspect the existing"):
        environment.prepare(root, ready["operation_id"])


@pytest.mark.parametrize(
    "change", ["source", "gguf", "model", "outside", "writable", "hardlink", "python", "receipt", "extra"]
)
def test_changed_engine_component_or_selection_cannot_be_adopted(fixture, change):
    root, ready, observed = prepare(fixture)
    folder = root / ready["relative_path"]
    selected = environment.resolve(root, observed)
    target = selected["wan_low_noise"].resolve()
    if change in {"source", "gguf"}:
        (folder / ("gguf-source" if change == "gguf" else "source") / "nodes.py").write_bytes(b"changed")
    elif change == "model":
        target.chmod(0o600)
        target.write_bytes(b"changed")
    elif change == "outside":
        selected["wan_low_noise"].unlink()
        selected["wan_low_noise"].symlink_to(root / "outside")
    elif change == "writable":
        target.chmod(0o644)
    elif change == "hardlink":
        os.link(target, root / "extra-link")
    elif change == "python":
        (folder / "venv/bin/python").unlink()
        (folder / "venv/bin/python").symlink_to("/usr/bin/python3")
    elif change == "receipt":
        (folder / "ready.json").write_text(json.dumps({**ready, "environment_prepared": False}))
    else:
        observed["command"] = "untrusted"
    with pytest.raises((ValueError, FileNotFoundError)):
        environment.resolve(root, observed)


def test_preparation_cancellation_or_failed_probe_cannot_publish_readiness(fixture, monkeypatch):
    root, _, calls = fixture

    def stopped():
        raise InterruptedError("Stopped")

    with pytest.raises(InterruptedError):
        environment.prepare(root, str(uuid4()), check=stopped)
    assert calls == [] and not list(root.rglob("ready.json"))
    command = environment.command

    def fail_probe(argv, *, folder, check):
        if any("svi_environment_probe.py" in item for item in argv):
            raise RuntimeError("Probe failed")
        return command(argv, folder=folder, check=check)

    monkeypatch.setattr(environment, "command", fail_probe)
    with pytest.raises(RuntimeError, match="Probe failed"):
        environment.prepare(root, str(uuid4()))
    assert not list(root.rglob("ready.json"))


def test_shared_identity_hides_private_setup_run_and_refuses_rebinding(fixture):
    root, ready, observed = prepare(fixture)
    public = environment.remember(root, observed)
    assert "operation_id" not in public and ready["operation_id"] not in json.dumps(public)
    assert environment.resolve_public(root, public)["observation"] == observed
    assert environment.remember(root, observed) == public
    path = root / "runtime/svi-environments/identities" / (public["environment_id"] + ".json")
    path.write_text(json.dumps({**observed, "operation_id": str(uuid4())}))
    with pytest.raises((ValueError, FileNotFoundError)):
        environment.resolve_public(root, public)
