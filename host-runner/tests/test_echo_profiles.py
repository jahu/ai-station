import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner.avatars import AvatarRequest
from pydantic import ValidationError


def body(**change):
    return AvatarRequest(
        run_id=uuid4(),
        image_relative="artifacts/portrait.png",
        audio_relative="artifacts/speech.wav",
        prompt="A person speaking",
        gpu=7,
        permissions=["filesystem_read", "workspace_write"],
        **change,
    )


@pytest.mark.parametrize("change", [{"size": 256}, {"size": 512}, {"steps": 4}])
def test_native_profile_rejects_unqualified_geometry_and_sampling(change):
    with pytest.raises(ValidationError, match="384x384"):
        body(memory_profile="bounded_11g", **change)


def test_legacy_native_request_does_not_acquire_a_profile_field():
    assert "memory_profile" not in body().model_dump(mode="json")
    assert "memory_profile" not in body(memory_profile="default").model_dump(mode="json")
    assert body(memory_profile="bounded_11g").model_dump(mode="json")["memory_profile"] == "bounded_11g"


@pytest.mark.parametrize("field", ["weight_dtype", "memory_limit", "command"])
def test_native_profile_is_not_a_loader_or_shell_control(field):
    with pytest.raises(ValidationError, match="Extra inputs"):
        body(**{field: "arbitrary"})


def test_product_entry_verifies_actual_kernel_scope_before_inference_import(tmp_path):
    package = Path(__file__).resolve().parents[1] / "ai_station_runner"
    env = {**os.environ, "PYTHONPATH": str(package.parent)}
    env.pop("AI_STATION_REAL_GPU_TESTS", None)
    output = tmp_path / "unqualified.mp4"
    result = subprocess.run(
        [
            sys.executable,
            str(package / "echomimic_entry.py"),
            "--runtime-dir",
            str(tmp_path / "uninstalled"),
            "--output-path",
            str(output),
            "--station-bounded-run-id",
            str(uuid4()),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and "outside its owned memory scope" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr and not output.exists()
