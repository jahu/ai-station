import json
import struct
from uuid import uuid4

import pytest
from ai_station_runner.avatars import AvatarRequest
from ai_station_runner.echo_motion import profile_key, validate_checkpoint
from pydantic import ValidationError


def checkpoint(path, **changes):
    shape = [1, 16, 5, 32, 32]
    size = 16 * 5 * 32 * 32 * 4
    header = {
        "motion": {"dtype": "F32", "shape": shape, "data_offsets": [0, size]},
        "__metadata__": {"station.echo_profile": "a" * 64},
    }
    header["motion"].update(changes)
    raw = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * size)
    return path


def test_bounded_echo_header_and_current_model_profile(tmp_path):
    path = checkpoint(tmp_path / "motion.safetensors")
    assert validate_checkpoint(path, 256, "a" * 64) == [1, 16, 5, 32, 32]
    with pytest.raises(ValueError, match="observation changed"):
        validate_checkpoint(path, 256, "b" * 64)
    with pytest.raises(ValueError, match="shape"):
        validate_checkpoint(path, 512, "a" * 64)


@pytest.mark.parametrize(
    "change",
    [
        {"dtype": "F16"},
        {"shape": [1, 48, 5, 32, 32]},
        {"shape": [True, 16, 5, 32, 32]},
        {"data_offsets": [8, 99]},
    ],
)
def test_echo_header_rejects_unexpected_tensor_layout(tmp_path, change):
    with pytest.raises(ValueError):
        validate_checkpoint(checkpoint(tmp_path / "bad.safetensors", **change), 256, "a" * 64)


def test_echo_header_rejects_unbounded_header_or_extra_payload(tmp_path):
    path = tmp_path / "bad.safetensors"
    path.write_bytes(struct.pack("<Q", 9000) + b"0" * 9001)
    with pytest.raises(ValueError, match="header"):
        validate_checkpoint(path, 256, "a" * 64)
    checkpoint(path)
    with path.open("ab") as f:
        f.write(b"extra")
    with pytest.raises(ValueError):
        validate_checkpoint(path, 256, "a" * 64)


def test_echo_profile_changes_when_model_observation_changes(tmp_path):
    files = [
        "config/config.yaml",
        "transformer/diffusion_pytorch_model.safetensors",
        "Wan2.1-Fun-V1.1-1.3B-InP/Wan2.1_VAE.pth",
        "Wan2.1-Fun-V1.1-1.3B-InP/models_t5_umt5-xxl-enc-bf16.pth",
        "Wan2.1-Fun-V1.1-1.3B-InP/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
    ]
    for name in files:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"model")
    original = profile_key(tmp_path, tmp_path)
    (tmp_path / files[2]).write_bytes(b"changed model")
    assert profile_key(tmp_path, tmp_path) != original


def test_echo_checkpoint_requires_full_job_and_preceding_video():
    media = {"relative_path": "artifacts/motion.safetensors", "sha256": "a" * 64, "size_bytes": 100}
    values = {
        "run_id": str(uuid4()),
        "motion_context": media,
        "image_relative": "artifacts/photo.png",
        "audio_relative": "artifacts/speech.wav",
        "prompt": "Speaking",
        "gpu": 0,
        "permissions": ["filesystem_read", "workspace_write"],
    }
    with pytest.raises(ValidationError, match="preceding full-job"):
        AvatarRequest(**values)
    with pytest.raises(ValidationError, match="preceding full-job"):
        AvatarRequest(**values, previous_video=media)
    AvatarRequest(**values, previous_video=media, audio_window={"start_frame": 64})


def test_continuation_uses_current_flow_noise_and_zero_noise_final_state():
    from ai_station_runner.echo_motion import flow_sigma

    scheduler = type("FlowUniPCMultistepScheduler", (), {"sigmas": [1.0, 0.6, 0.0]})()
    assert flow_sigma(scheduler, 1) == 0.6
    assert flow_sigma(scheduler, 2) == 0
    with pytest.raises(ValueError):
        flow_sigma(scheduler, True)
    with pytest.raises(ValueError):
        flow_sigma(scheduler, 3)
    with pytest.raises(ValueError):
        flow_sigma(type("UnknownScheduler", (), {"sigmas": [0.5]})(), 0)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_flow_continuation_rejects_invalid_noise_levels(value):
    from ai_station_runner.echo_motion import flow_sigma

    scheduler = type("FlowUniPCMultistepScheduler", (), {"sigmas": [value]})()
    with pytest.raises(ValueError):
        flow_sigma(scheduler, 0)
