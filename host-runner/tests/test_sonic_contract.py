"""No inference: qualify observations, complete timing and source boundaries."""

import json
import wave
from uuid import uuid4

import pytest
from ai_station_runner import sonic_contract as contract
from ai_station_runner.security import PathBoundaryError
from PIL import Image


def media(path, root):
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": contract.digest(path),
    }


@pytest.fixture
def inputs(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    portrait, audio = artifacts / "portrait.png", artifacts / "speech.wav"
    Image.new("RGB", (512, 768), "white").save(portrait)
    with wave.open(str(audio), "wb") as source:
        source.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        source.writeframes(b"\x00" * (16321 * 2))
    return tmp_path, portrait, audio


def request(inputs):
    root, portrait, audio = inputs
    return {
        "version": 1,
        "run_id": str(uuid4()),
        "recipe": {"id": contract.PROFILE, "observation": "c" * 64},
        "portrait": media(portrait, root),
        "audio": media(audio, root),
        "observed_input": contract.inspect_inputs(root, media(portrait, root), media(audio, root)),
        "seed": 43,
        "device_count": 2,
        "deadline_at": 2000,
        "permissions": ["filesystem_read", "workspace_write"],
    }


def test_whole_recording_retains_non_integral_tail_and_native_portrait(inputs):
    root, portrait, audio = inputs
    observed = contract.inspect_inputs(root, media(portrait, root), media(audio, root))
    assert observed == {
        "width": 512,
        "height": 768,
        "samples": 16321,
        "sample_rate": 24000,
        "channels": 1,
        "sample_width": 2,
        "target_frames": 18,
        "base_frames": 9,
        "endpoint_frames": 1,
    }


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "size",
        "replace-same-size",
        "absolute",
        "traversal",
        "symlink",
        "noncanonical",
        "backslash",
        "outside-artifacts",
        "bool-size",
    ],
)
def test_media_identity_cannot_follow_changed_bytes_or_paths(inputs, change):
    root, portrait, _ = inputs
    value = media(portrait, root)
    if change == "hash":
        value["sha256"] = "f" * 64
    elif change == "size":
        value["size_bytes"] += 1
    elif change == "replace-same-size":
        contents = bytearray(portrait.read_bytes())
        contents[-1] ^= 1
        portrait.write_bytes(contents)
    elif change == "absolute":
        value["relative_path"] = str(portrait)
    elif change == "traversal":
        value["relative_path"] = "artifacts/../artifacts/portrait.png"
    elif change == "symlink":
        target = root / "artifacts/link.png"
        target.symlink_to(portrait)
        value["relative_path"] = "artifacts/link.png"
    elif change == "noncanonical":
        value["relative_path"] = "artifacts//portrait.png"
    elif change == "backslash":
        value["relative_path"] = "artifacts/\\portrait.png"
    elif change == "outside-artifacts":
        value["relative_path"] = "runs/portrait.png"
    else:
        value["size_bytes"] = True
    with pytest.raises((ValueError, PathBoundaryError)):
        contract.checked_media(root, value)


def test_exif_orientation_is_frozen_before_selecting_the_canvas(inputs):
    root, portrait, audio = inputs
    portrait = portrait.with_suffix(".jpg")
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (768, 512), "white").save(portrait, exif=exif)
    observation = contract.inspect_inputs(root, media(portrait, root), media(audio, root))
    assert (observation["width"], observation["height"]) == (512, 768)


@pytest.mark.parametrize(
    "fault", ["truncated-audio", "three-channels", "too-short", "image-format", "oversized-geometry"]
)
def test_input_inspection_rejects_invalid_sources_before_inference(inputs, fault):
    root, portrait, audio = inputs
    if fault == "truncated-audio":
        audio.write_bytes(audio.read_bytes()[:-2])
    elif fault in {"three-channels", "too-short"}:
        with wave.open(str(audio), "wb") as target:
            channels = 3 if fault == "three-channels" else 1
            target.setparams((channels, 2, 24000, 0, "NONE", "not compressed"))
            target.writeframes(b"\x00" * ((16321 if channels == 3 else 100) * channels * 2))
    elif fault == "image-format":
        Image.new("RGB", (512, 768)).save(portrait, format="BMP")
    else:
        Image.new("RGB", (32, 256)).save(portrait)
    with pytest.raises(ValueError):
        contract.inspect_inputs(root, media(portrait, root), media(audio, root))


def test_internal_request_is_json_portable_and_exact(inputs, monkeypatch):
    monkeypatch.setattr(contract.time, "time", lambda: 1000)
    body = request(inputs)
    assert contract.checked_request(json.loads(json.dumps(body))) == body


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", True),
        ("version", 2),
        ("run_id", "../another-run"),
        ("seed", True),
        ("seed", -1),
        ("seed", 2**31),
        ("device_count", True),
        ("device_count", 0),
        ("device_count", 3),
        ("deadline_at", True),
        ("deadline_at", float("nan")),
        ("deadline_at", float("inf")),
        ("deadline_at", 999),
        ("deadline_at", 15401),
        ("command", "arbitrary"),
        ("model_path", "/outside"),
        ("recipe", None),
        ("recipe", {"id": "legacy", "observation": "c" * 64}),
        ("permissions", []),
        ("permissions", ["filesystem_read", "filesystem_read"]),
        ("permissions", ["filesystem_read", "network_external"]),
    ],
)
def test_internal_request_is_not_an_unbounded_model_or_shell_api(inputs, monkeypatch, key, value):
    monkeypatch.setattr(contract.time, "time", lambda: 1000)
    body = {**request(inputs), key: value}
    with pytest.raises(ValueError):
        contract.checked_request(body)


@pytest.mark.parametrize(
    "change",
    [
        {"samples": True},
        {"sample_rate": 7999},
        {"target_frames": 17},
        {"base_frames": 8},
        {"endpoint_frames": 0},
        {"channels": 3},
        {"width": 513},
        {"width": 128},
        {"width": 768, "height": 768},
        {"unexpected": 1},
    ],
)
def test_unqualified_canvas_or_audio_observation_does_not_start_a_model(inputs, monkeypatch, change):
    monkeypatch.setattr(contract.time, "time", lambda: 1000)
    body = request(inputs)
    body["observed_input"].update(change)
    with pytest.raises(ValueError):
        contract.checked_request(body)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    # Tiny complete stand-ins: these tests never import or download model code.
    runtime, models, adapter = (tmp_path / part for part in ("runtime", "models", "adapter"))
    for root, names in (
        (
            runtime,
            (
                "sonic.py",
                "config/inference/sonic.yaml",
                "src/pipelines/pipeline_sonic.py",
                "src/dataset/test_preprocess.py",
                "src/other.py",
            ),
        ),
        (models, contract.MODEL_FILES),
        (adapter, contract.IMPLEMENTATION_FILES),
    ):
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed tiny fixture")
    monkeypatch.setattr(contract, "__file__", str(adapter / "sonic_contract.py"))
    return runtime, models, adapter


@pytest.mark.parametrize("kind", ["source", "model", "adapter"])
def test_observation_binds_actual_same_size_content_not_just_filenames(installation, kind):
    runtime, models, adapter = installation
    before = contract.installation_observation(runtime, models)
    path = {
        "source": runtime / "src/other.py",
        "model": models / contract.MODEL_FILES[0],
        "adapter": adapter / contract.IMPLEMENTATION_FILES[0],
    }[kind]
    path.write_text("FIXED tiny fixture")
    assert contract.installation_observation(runtime, models) != before


def test_observation_has_no_machine_path_or_timestamp_in_its_identity(installation, tmp_path):
    import shutil

    runtime, models, _ = installation
    runtime2, models2 = tmp_path / "portable-runtime", tmp_path / "portable-models"
    shutil.copytree(runtime, runtime2)
    shutil.copytree(models, models2)
    assert contract.installation_observation(runtime, models) == contract.installation_observation(
        runtime2, models2
    )


@pytest.mark.parametrize(
    "fault", ["model-missing", "source-symlink", "source-directory-symlink", "model-symlink"]
)
def test_uninspected_imports_or_weights_are_rejected(installation, tmp_path, fault):
    runtime, models, _ = installation
    path = models / contract.MODEL_FILES[0]
    if fault == "model-missing":
        path.unlink()
    elif fault == "source-symlink":
        path = runtime / "src/other.py"
        path.unlink()
        path.symlink_to(runtime / "sonic.py")
    elif fault == "source-directory-symlink":
        (runtime / "src/imported").symlink_to(tmp_path, target_is_directory=True)
    else:
        path.unlink()
        path.symlink_to(models / contract.MODEL_FILES[1])
    with pytest.raises((OSError, ValueError)):
        contract.installation_observation(runtime, models)
