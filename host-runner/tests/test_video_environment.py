"""Fixed offline video assembly with tiny synthetic inputs and no subprocess/GPU."""

import hashlib
import json
import os
from uuid import uuid4

import pytest
from ai_station_runner import video_environment as environment


def test_reviewed_video_recipe_has_one_coherent_dependency_set():
    value = environment.recipe()
    assert len(value["inputs"]) == 102
    versions = {v["name"]: v["version"] for v in value["inputs"] if v["kind"] == "wheel"}
    assert len(versions) == 97
    assert versions["torch"] == versions["torchaudio"] == "2.11.0"
    assert versions["torchvision"] == "0.26.0"
    assert sum(v["size_bytes"] for v in value["inputs"] if v["kind"] == "model") == 18144966705


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    items = []
    for filename, kind, role in [
        ("python.tar.gz", "python", None),
        ("sdk.tar.gz", "sdk", None),
        ("fixture-1.0-py3-none-any.whl", "wheel", None),
        *[(name + ".safetensors", "model", name) for name in sorted(environment.ROLES)],
    ]:
        content = filename.encode()
        sha = hashlib.sha256(content).hexdigest()
        (store / sha).write_bytes(content)
        (store / sha).chmod(0o444)
        item = dict(filename=filename, kind=kind, sha256=sha, size_bytes=len(content))
        if role:
            item["role"] = role
        if kind == "wheel":
            item.update(name="fixture", version="1.0")
        items.append(item)
    content = b"# fixed headless SDK"
    frozen = dict(
        profile=environment.PROFILE,
        inputs=items,
        source_sha256=environment.fingerprint(
            [dict(path="nodes.py", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())]
        ),
    )
    monkeypatch.setattr(environment, "recipe", lambda: frozen)

    def unpack_python(_object, folder, check):
        path = folder / "python/bin/python3.12"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"fake Python; never executed")
        path.chmod(0o700)
        return path

    def unpack_source(_object, folder, check):
        source = folder / "fixed-sdk"
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


def test_offline_install_publishes_readiness_only_after_probe_and_resolves_exact_inputs(fixture):
    root, frozen, calls = fixture
    receipt = environment.prepare(root, str(uuid4()))
    observation = {k: receipt[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    selected = environment.resolve(root, observation)
    assert (
        selected["managed"]
        and selected["video_python"].resolve() == selected["environment"] / "python/bin/python3.12"
    )
    assert set(environment.ROLES) <= selected.keys() and receipt["video_inference_tested"] is False
    install = next(argv for argv in calls if "install" in argv)
    assert {"--no-index", "--no-deps", "--require-hashes", "--only-binary"} <= set(install)
    assert any("video_environment_probe.py" in arg for arg in calls[-1])
    for item in frozen["inputs"]:
        if item["kind"] == "model":
            assert selected[item["role"]].resolve() == root / "models/store" / item["sha256"]
    with pytest.raises(ValueError, match="Inspect the existing"):
        environment.prepare(root, receipt["operation_id"])


@pytest.mark.parametrize(
    "change", ["weights", "source", "outside", "hardlink", "writable", "receipt", "extra_observation"]
)
def test_changed_models_source_or_frozen_identity_cannot_be_selected(fixture, change):
    root, frozen, _ = fixture
    receipt = environment.prepare(root, str(uuid4()))
    folder = root / receipt["relative_path"]
    observation = {k: receipt[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    item = next(v for v in frozen["inputs"] if v["kind"] == "model")
    link = folder / "models" / item["filename"]
    target = link.resolve()
    if change == "weights":
        target.chmod(0o600)
        target.write_bytes(b"bad")
    elif change == "writable":
        target.chmod(0o600)
    elif change == "hardlink":
        os.link(target, root / "extra-link")
    elif change == "outside":
        link.unlink()
        link.symlink_to(root / "outside")
    elif change == "source":
        (folder / "source/nodes.py").write_bytes(b"changed SDK")
    elif change == "receipt":
        (folder / "ready.json").write_text(json.dumps({**receipt, "environment_prepared": False}))
    else:
        observation["command"] = "anything"
    with pytest.raises((ValueError, FileNotFoundError)):
        environment.resolve(root, observation)


def test_cancellation_or_invalid_inputs_cannot_execute_or_publish(fixture):
    root, frozen, calls = fixture

    def stopped():
        raise InterruptedError("Stopped")

    with pytest.raises(InterruptedError):
        environment.prepare(root, str(uuid4()), check=stopped)
    assert calls == [] and not list(root.rglob("ready.json"))
    (root / "models/store" / frozen["inputs"][0]["sha256"]).chmod(0o600)
    with pytest.raises(ValueError):
        environment.prepare(root, str(uuid4()))
    assert calls == [] and not list(root.rglob("ready.json"))


def test_shared_video_identity_hides_private_preparation_run_and_cannot_be_rebound(fixture):
    root, _, _ = fixture
    ready = environment.prepare(root, str(uuid4()))
    private = {k: ready[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    public = environment.remember(root, private)
    assert "operation_id" not in public and ready["operation_id"] not in json.dumps(public)
    assert set(public) == {"profile", "manifest_sha256", "environment_id"}
    assert environment.remember(root, private) == public
    assert environment.resolve_public(root, public)["observation"] == private
    path = root / "runtime/video-environments/identities" / (public["environment_id"] + ".json")
    path.write_text(json.dumps({**private, "operation_id": str(uuid4())}))
    with pytest.raises(ValueError):
        environment.resolve_public(root, public)
