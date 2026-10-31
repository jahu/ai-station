"""Fixed offline avatar assembly with tiny synthetic inputs and no subprocess/GPU."""

import hashlib
import json
import os
from uuid import uuid4

import pytest
from ai_station_runner import avatar_environment as environment


def test_reviewed_avatar_recipe_has_one_coherent_dependency_set():
    value = environment.recipe()
    assert len(value["inputs"]) == 92
    versions = {v["name"]: v["version"] for v in value["inputs"] if v["kind"] == "wheel"}
    assert len(versions) == 75
    assert versions["torch"] == "2.14.0"
    assert versions["torchvision"] == "0.29.0"
    assert sum(v["size_bytes"] for v in value["inputs"] if v["kind"] == "model") == 8315655620


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    items = []
    for filename, kind, role in [
        ("python.tar.gz", "python", None),
        ("sdk.tar.gz", "sdk", None),
        ("fixture-1.0-py3-none-any.whl", "wheel", None),
        *[(name, "model", name) for name in ["Sonic/unet.pth", "whisper-tiny/config.json"]],
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
            [
                dict(
                    path="config/inference/sonic.yaml",
                    size_bytes=5,
                    sha256=hashlib.sha256(b"fixed").hexdigest(),
                ),
                dict(path="sonic.py", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest()),
            ]
        ),
    )
    monkeypatch.setattr(environment, "recipe", lambda: frozen)

    def unpack_python(_object, folder, check, **kwargs):
        path = folder / "python/bin/python3.10"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"fake Python; never executed")
        path.chmod(0o700)
        return path

    def unpack_source(_object, folder, check):
        source = folder / "fixed-sdk"
        source.mkdir()
        (source / "sonic.py").write_bytes(content)
        (source / "config/inference").mkdir(parents=True)
        (source / "config/inference/sonic.yaml").write_bytes(b"fixed")
        return source

    calls = []

    def command(argv, *, folder, check):
        check()
        calls.append(argv)
        if "venv" in argv:
            path = folder / "venv/bin/python"
            path.parent.mkdir(parents=True)
            path.symlink_to(folder / "python/bin/python3.10")
        if any("avatar_environment_probe.py" in arg for arg in argv):
            binary = folder / "venv/lib/python3.10/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-fixture"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"fake FFmpeg; never executed")
            binary.chmod(0o700)
            (folder / "bin/ffmpeg").symlink_to(binary)

    monkeypatch.setattr(environment.avatar_source_wheel, "build", lambda *args, **kwargs: [])
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
        and selected["sonic_python"].resolve() == selected["environment"] / "python/bin/python3.10"
    )
    assert (
        selected["sonic_models"] == selected["environment"] / "models"
        and receipt["avatar_inference_tested"] is False
    )
    install = next(argv for argv in calls if "install" in argv)
    assert {"--no-index", "--no-deps", "--require-hashes", "--only-binary"} <= set(install)
    assert any("avatar_environment_probe.py" in arg for arg in calls[-1])
    for item in frozen["inputs"]:
        if item["kind"] == "model":
            assert (selected["sonic_models"] / item["filename"]).resolve() == root / "models/store" / item[
                "sha256"
            ]
    with pytest.raises(ValueError, match="Inspect"):
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
        (folder / "source/sonic.py").write_bytes(b"changed SDK")
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


@pytest.mark.parametrize("change", ["missing", "outside", "not_executable", "duplicate", "regular"])
def test_changed_finishing_codec_rejected_before_avatar_dispatch(fixture, change):
    root, _, _ = fixture
    ready = environment.prepare(root, str(uuid4()))
    folder = root / ready["relative_path"]
    codec = folder / "bin/ffmpeg"
    binary = codec.resolve()
    if change == "not_executable":
        binary.chmod(0o600)
    elif change == "duplicate":
        (binary.parent / "ffmpeg-linux-extra").write_bytes(b"ambiguous")
    else:
        codec.unlink()
        if change == "outside":
            external = root / "ambient-ffmpeg"
            external.write_bytes(b"unrelated")
            external.chmod(0o700)
            codec.symlink_to(external)
        elif change == "regular":
            codec.write_bytes(b"unreviewed")
            codec.chmod(0o700)
    observation = {k: ready[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    with pytest.raises(ValueError, match="prepared offline FFmpeg"):
        environment.resolve(root, observation)


def test_shared_avatar_identity_hides_private_run_and_cannot_be_rebound(fixture):
    root, _, _ = fixture
    ready = environment.prepare(root, str(uuid4()))
    private = {k: ready[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    environment.remember(root, private)
    identity = environment.environment_id(private)
    assert ready["operation_id"] not in identity
    assert environment.resolve_id(root, identity)["observation"] == private
    path = root / "runtime/avatar-environments/identities" / (identity + ".json")
    path.write_text(json.dumps({**private, "operation_id": str(uuid4())}))
    with pytest.raises(ValueError):
        environment.resolve_id(root, identity)


def test_only_exact_managed_model_links_cross_the_legacy_boundary(fixture):
    from ai_station_runner.sonic_contract import direct_file

    root, _, _ = fixture
    ready = environment.prepare(root, str(uuid4()))
    models = root / ready["relative_path"] / "models"
    expected = models / "Sonic/unet.pth"
    assert direct_file(models, "Sonic/unet.pth") == expected
    with pytest.raises(ValueError):
        direct_file(models, "../source/sonic.py")
    external = root / "external"
    external.mkdir()
    (external / "alias.pth").symlink_to(expected.resolve())
    with pytest.raises(ValueError):
        direct_file(external, "alias.pth")
