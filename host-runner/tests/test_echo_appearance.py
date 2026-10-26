import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner.avatars import AvatarRequest
from ai_station_runner.echo_appearance import (
    PROFILE,
    anchored_conditioning,
    checked_recipe,
    current_recipe,
    motion_profile,
)
from ai_station_runner.echo_motion import profile_key
from pydantic import ValidationError


def installation(root):
    for name in (
        "config/config.yaml",
        "transformer/diffusion_pytorch_model.safetensors",
        "Wan2.1-Fun-V1.1-1.3B-InP/Wan2.1_VAE.pth",
        "Wan2.1-Fun-V1.1-1.3B-InP/models_t5_umt5-xxl-enc-bf16.pth",
        "Wan2.1-Fun-V1.1-1.3B-InP/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
        "infer_flash.py",
        "src/utils.py",
        "src/pipeline_wan_fun_inpaint_audio_2512.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"disposable model or source")


def test_new_checkpoint_identity_binds_appearance_without_rewriting_legacy(tmp_path):
    installation(tmp_path)
    legacy = profile_key(tmp_path, tmp_path)
    recipe = current_recipe(tmp_path, tmp_path)
    assert motion_profile(tmp_path, tmp_path) == legacy
    assert motion_profile(tmp_path, tmp_path, recipe) != legacy
    (tmp_path / "src/utils.py").write_bytes(b"changed color and conditioning implementation")
    assert profile_key(tmp_path, tmp_path) == legacy
    assert current_recipe(tmp_path, tmp_path) != recipe
    with pytest.raises(ValueError, match="observation changed"):
        motion_profile(tmp_path, tmp_path, recipe)


@pytest.mark.parametrize(
    "recipe",
    [
        {"id": "arbitrary", "observation": "a" * 64},
        {"id": PROFILE, "observation": True},
        {"id": PROFILE, "observation": "bad"},
        {"id": PROFILE, "observation": "a" * 64, "command": "shell"},
        [],
    ],
)
def test_only_one_fixed_observed_recipe_is_accepted(recipe):
    with pytest.raises(ValueError):
        checked_recipe(recipe)


def test_anchor_preserves_original_identity_and_passes_other_upstream_arguments():
    portrait = object()
    seen = []

    def upstream(start, end, **kwargs):
        seen.append((start, end, kwargs))
        return "pixels", "mask", portrait

    assert anchored_conditioning(upstream, portrait, None, video_length=81, sample_size=[384, 384]) == (
        "pixels",
        "mask",
        portrait,
    )
    assert seen == [(portrait, portrait, {"video_length": 81, "sample_size": [384, 384]})]
    with pytest.raises(ValueError):
        anchored_conditioning(upstream, None, None)
    with pytest.raises(ValueError):
        anchored_conditioning(upstream, portrait, object())
    assert len(seen) == 1


def test_recipe_requires_full_job_and_legacy_request_serialization_stays_unchanged():
    values = {
        "run_id": uuid4(),
        "image_relative": "artifacts/portrait.png",
        "audio_relative": "artifacts/speech.wav",
        "prompt": "Speaking",
        "gpu": 7,
        "permissions": ["filesystem_read", "workspace_write"],
    }
    assert "appearance_recipe" not in AvatarRequest(**values).model_dump(mode="json")
    recipe = {"id": PROFILE, "observation": "a" * 64}
    with pytest.raises(ValidationError, match="full-job"):
        AvatarRequest(**values, appearance_recipe=recipe)
    accepted = AvatarRequest(**values, appearance_recipe=recipe, audio_window={"start_frame": 0})
    assert accepted.model_dump(mode="json")["appearance_recipe"] == recipe


def test_changed_recipe_fails_before_importing_the_installed_inference(tmp_path):
    installation(tmp_path)
    entry = Path(__file__).resolve().parents[1] / "ai_station_runner/echomimic_entry.py"
    result = subprocess.run(
        [
            sys.executable,
            str(entry),
            "--runtime-dir",
            str(tmp_path),
            "--output-path",
            str(tmp_path / "output.mp4"),
            "--model_name",
            str(tmp_path / "Wan2.1-Fun-V1.1-1.3B-InP"),
            "--sample_size",
            "384",
            "384",
            "--appearance-profile",
            PROFILE,
            "--appearance-observation",
            "b" * 64,
            "--motion-output",
            str(tmp_path / "motion.safetensors"),
            "--motion-profile",
            "b" * 64,
        ],
        env={**os.environ, "PYTHONPATH": str(entry.parent.parent)},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert (
        result.returncode != 0 and "appearance implementation or model observation changed" in result.stderr
    )
    assert "SyntaxError" not in result.stderr and "ModuleNotFoundError" not in result.stderr
    assert not (tmp_path / "output.mp4").exists() and not (tmp_path / "motion.safetensors").exists()
