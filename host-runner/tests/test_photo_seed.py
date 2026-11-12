"""Observe actual argv received by a fake sd-cli, without loading any model."""

import json
import subprocess
import sys

import pytest
from ai_station_runner.photo import PhotoCommandError, build_photo_argv
from test_photo_runtime_selection import arguments


@pytest.mark.parametrize("mode", ["t2i", "img2img", "recompose"])
@pytest.mark.parametrize("seed", [0, 43, 4294967295])
@pytest.mark.parametrize("profile", ["pipeline", "direct"])
@pytest.mark.parametrize("override_runtime", [False, True])
def test_qwen_seed_reaches_real_child_without_modifying_external_pipeline(
    tmp_path, mode, seed, profile, override_runtime
):
    executable = tmp_path / "sd-cli"
    executable.write_text(f"#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
    executable.chmod(0o700)
    script = tmp_path / "pipeline.py"
    source = f"""import subprocess,sys
from pathlib import Path
SDCLI=Path({str(tmp_path / "unused-engine") if override_runtime else str(executable)!r})
PHOTO_SUFFIX=T2I_NEGATIVE=IDENTITY_PREFIX=RECOMPOSE_PREFIX_SINGLE=RECOMPOSE_PREFIX_MULTI='original'
def main():
    subprocess.run([str(SDCLI), '-p', '--station-seed', '-r', 'input.png'], check=True)
"""
    script.write_text(source)
    options = arguments(tmp_path, mode)
    options.update(
        seed=seed,
        prompt_style="pipeline" if profile == "pipeline" else "prompt" if mode == "t2i" else "instruction",
    )
    if override_runtime:
        options["sd_cli"] = str(executable)
    argv = build_photo_argv(sys.executable, str(script), **options)
    result = subprocess.run(argv, check=True, text=True, capture_output=True)
    actual = json.loads(result.stdout.splitlines()[-1])
    assert actual == ["-p", "--station-seed", "-r", "input.png", "--seed", str(seed)]
    assert script.read_text() == source


@pytest.mark.parametrize("seed", [-1, 4294967296, True, "43; false", 1.2])
def test_seed_rejects_noninteger_or_out_of_bounds_values(tmp_path, seed):
    with pytest.raises(PhotoCommandError, match="seed"):
        build_photo_argv(
            sys.executable,
            str(tmp_path / "pipeline.py"),
            **{**arguments(tmp_path, "recompose"), "seed": seed},
        )
