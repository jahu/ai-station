import hashlib
import json
import os
from uuid import uuid4

import pytest
from ai_station_runner import fish_environment as environment


def test_fixed_recipe_keeps_incompatible_protobufs_in_separate_complete_environments():
    value = environment.recipe()
    assert len(value["inputs"]) == 163
    fish = {v["name"].lower(): v["version"] for v in value["dependency_groups"]["fish"]}
    asr = {v["name"].lower(): v["version"] for v in value["dependency_groups"]["transcription"]}
    assert fish["protobuf"] == "3.19.6" and asr["protobuf"] != fish["protobuf"]
    assert len(fish) == 133 and len(asr) == 23
    assert set(environment.whisper_manifest(value)["files"]) == environment.ASR_FILES


@pytest.mark.parametrize("fault", ["part", "source", "role", "dependencies", "model", "wheel"])
def test_changed_recipe_is_rejected_before_any_preparation(tmp_path, monkeypatch, fault):
    value = environment.recipe()
    if fault == "part":
        value["inputs"].pop()
    elif fault == "source":
        value["source_sha256"] = "0" * 64
    elif fault == "role":
        value["inputs"][0]["environments"] = ["untrusted"]
    elif fault == "dependencies":
        value["dependency_groups"]["transcription"] = value["dependency_groups"]["fish"]
    elif fault == "model":
        next(v for v in value["inputs"] if v.get("model_group") == "fish")["sha256"] = "0" * 64
    else:
        value["derived_wheels"]["randomname"]["sha256"] = "0" * 64
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(value))
    monkeypatch.setattr(environment, "RECIPE", path)
    with pytest.raises(ValueError):
        environment.recipe()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    items = []
    for filename, kind, groups, logical in [
        ("python.tar.gz", "python", ["fish", "transcription"], None),
        ("sdk.tar.gz", "sdk", ["fish"], None),
        ("fish-1.0-py3-none-any.whl", "wheel", ["fish"], None),
        ("asr-1.0-py3-none-any.whl", "wheel", ["transcription"], None),
        ("fish--config.json", "model", ["fish"], "config.json"),
        ("transcription--model.bin", "model", ["transcription"], "model.bin"),
    ]:
        content = filename.encode()
        sha = hashlib.sha256(content).hexdigest()
        (store / sha).write_bytes(content)
        (store / sha).chmod(0o444)
        item = dict(filename=filename, kind=kind, environments=groups, sha256=sha, size_bytes=len(content))
        if logical:
            item.update(model_filename=logical, model_group=groups[0])
        if kind == "wheel":
            item.update(name=groups[0], version="1.0")
        items.append(item)
    frozen = dict(profile=environment.PROFILE, inputs=items, transcription_revision="fixed")
    monkeypatch.setattr(environment, "recipe", lambda: frozen)
    source = hashlib.sha256()
    name = b"fish_speech/fixed.py"
    source.update(len(name).to_bytes(4, "big"))
    source.update(name)
    source.update(hashlib.sha256(b"fixed SDK").digest())
    monkeypatch.setattr(environment, "SOURCE_SHA256", source.hexdigest())

    def unpack_python(_object, folder, check, **kwargs):
        path = folder / "python/bin/python3.12"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic interpreter; never executed")
        path.chmod(0o700)
        return path

    def unpack_source(_object, folder, check):
        path = folder / "fixed-sdk"
        (path / "fish_speech").mkdir(parents=True)
        (path / "fish_speech/fixed.py").write_bytes(b"fixed SDK")
        return path

    calls = []

    def command(argv, *, folder, check):
        check()
        calls.append((argv, folder))
        if "venv" in argv:
            path = folder / "venv/bin/python"
            path.parent.mkdir(parents=True)
            path.symlink_to(folder / "python/bin/python3.12")

    monkeypatch.setattr(environment.fish_source_wheels, "build", lambda *a, **kw: [])
    monkeypatch.setattr(environment, "unpack_python", unpack_python)
    monkeypatch.setattr(environment, "unpack_tar", unpack_source)
    monkeypatch.setattr(environment, "command", command)
    return tmp_path, frozen, calls


def test_complete_dual_install_resolves_private_interpreters_and_exact_model_views(fixture):
    root, frozen, calls = fixture
    receipt = environment.prepare(root, str(uuid4()))
    observation = {k: receipt[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    selected = environment.resolve(root, observation)
    assert selected["managed"] and receipt["fish_inference_tested"] is False
    assert selected["fish_speech_python"].resolve() != selected["transcription_python"].resolve()
    installs = [(args, folder) for args, folder in calls if "install" in args]
    assert {folder.name for _, folder in installs} == {"fish", "transcription"}
    for args, _ in installs:
        assert {"--no-index", "--no-deps", "--require-hashes", "--only-binary"} <= set(args)
    for group in ["fish", "transcription"]:
        path = selected["environment"] / group
        lock = (path / "requirements.lock").read_text()
        assert f"{group}==1.0" in lock
        assert ("asr==1.0" if group == "fish" else "fish==1.0") not in lock
        assert any(args[-1] == group and "fish_environment_probe.py" in args[-3] for args, _ in calls)
        models = selected["environment"] / "models" / group
        item = next(v for v in frozen["inputs"] if v.get("model_group") == group)
        assert (
            environment.model_reference(models, item["model_filename"]).resolve()
            == root / "models/store" / item["sha256"]
        )
        with pytest.raises(ValueError, match="outside"):
            environment.model_reference(models, "unapproved.bin")
    with pytest.raises(ValueError, match="Inspect"):
        environment.prepare(root, receipt["operation_id"])


@pytest.mark.parametrize(
    "fault", ["weights", "writable", "hardlink", "outside", "source", "receipt", "manifest", "authority"]
)
def test_changed_model_source_receipt_or_transcription_manifest_cannot_resolve(fixture, fault):
    root, frozen, _ = fixture
    receipt = environment.prepare(root, str(uuid4()))
    folder = root / receipt["relative_path"]
    observation = {k: receipt[k] for k in ["profile", "manifest_sha256", "operation_id"]}
    item = next(v for v in frozen["inputs"] if v.get("model_group") == "transcription")
    link = folder / "models/transcription" / item["model_filename"]
    target = link.resolve()
    if fault == "weights":
        target.chmod(0o600)
        target.write_bytes(b"changed")
    elif fault == "writable":
        target.chmod(0o600)
    elif fault == "hardlink":
        os.link(target, root / "duplicate")
    elif fault == "outside":
        link.unlink()
        link.symlink_to(root / "outside.bin")
    elif fault == "source":
        (folder / "source/fish_speech/fixed.py").write_bytes(b"changed")
    elif fault == "receipt":
        (folder / "ready.json").write_text(json.dumps({**receipt, "environment_prepared": False}))
    elif fault == "manifest":
        (folder / "models/transcription/ai-station-model.json").write_text("{}")
    else:
        observation["command"] = "unapproved"
    with pytest.raises((ValueError, FileNotFoundError)):
        environment.resolve(root, observation)


def test_stop_during_either_environment_probe_never_publishes_readiness(fixture, monkeypatch):
    root, frozen, _ = fixture
    original = environment.command

    def interrupted(args, **kwargs):
        if args[-1] == "transcription":
            raise InterruptedError("Owned setup stopped")
        return original(args, **kwargs)

    monkeypatch.setattr(environment, "command", interrupted)
    rid = str(uuid4())
    with pytest.raises(InterruptedError):
        environment.prepare(root, rid)
    assert not (
        root / "runtime/fish-environments" / environment.fingerprint(frozen) / rid / "ready.json"
    ).exists()


def test_opaque_identity_and_standard_library_model_view_remain_bound_to_prepared_operation(
    fixture, monkeypatch
):
    from ai_station_runner import fish_model_views as views

    root, frozen, _ = fixture
    monkeypatch.setattr(views, "view_recipe", lambda: frozen)
    receipt = environment.prepare(root, str(uuid4()))
    observed = {key: receipt[key] for key in ("profile", "manifest_sha256", "operation_id")}
    environment.remember(root, observed)
    identity = environment.environment_id(observed)
    folder = root / receipt["relative_path"]
    assert views.environment_directory(root, identity) == folder
    assert views.model_reference(folder / "models/transcription", "model.bin").is_file()
    assert environment.resolve_id(root, identity)["environment"] == folder
    mapping = root / "runtime/fish-environments/identities" / (identity + ".json")
    mapping.write_text(json.dumps({**observed, "operation_id": str(uuid4())}))
    with pytest.raises(ValueError, match="identity"):
        views.environment_directory(root, identity)
    with pytest.raises(ValueError, match="identity"):
        environment.resolve_id(root, identity)
    (folder / "ready.json").unlink()
    with pytest.raises(FileNotFoundError):
        views.model_reference(folder / "models/transcription", "model.bin")


@pytest.mark.parametrize("field", ["transcription_python", "transcription_model_dir"])
def test_partial_explicit_transcription_settings_keep_priority_over_managed_models(
    tmp_path, monkeypatch, field
):
    from types import SimpleNamespace

    from ai_station_runner import fish_selection

    settings = SimpleNamespace(
        transcription_python="", transcription_model_dir="", host_data_dir=lambda: tmp_path
    )
    setattr(settings, field, str(tmp_path / "external"))
    monkeypatch.setattr(
        fish_selection,
        "managed",
        lambda *a: pytest.fail("Do not replace explicit transcription configuration"),
    )
    selected = fish_selection.transcription_selection(settings, "a" * 64)
    assert selected["managed"] is False and selected[field] == tmp_path / "external"
    other = next(key for key in fish_selection.ASR_FIELDS if key != field)
    assert selected[other] is None
