"""Typed configured whole-recording launcher using the owned ProcessManager.

The public native adapter stays disabled unless explicitly configured. Real-GPU
qualification is a separate opt-in entry through this same launch contract.
"""

import json
import os
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.memory_scope import scope_environment, scope_prefix
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child
from ai_station_runner.sonic_contract import (
    checked_recipe,
    checked_request,
    inspect_inputs,
    installation_observation,
)


class WholeAvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    recipe: dict[str, str]
    portrait: MediaInput
    audio: MediaInput
    observed_input: dict[str, StrictInt]
    seed: StrictInt = Field(ge=0, le=2147483647)
    gpus: list[StrictInt] = Field(min_length=1, max_length=2)
    deadline_at: float = Field(gt=0, allow_inf_nan=False, strict=True)
    permissions: list[str] = Field(max_length=2)

    @model_validator(mode="after")
    def frozen_request(self):
        if len(set(self.gpus)) != len(self.gpus) or any(gpu < 0 for gpu in self.gpus):
            raise ValueError("Choose distinct allocated GPU indexes")
        checked_recipe(self.recipe)
        # Deserialize an existing receipt even after its deadline. Inspection
        # never starts a new process; fresh dispatch enforces time below.
        checked_request(self.native_request(), check_deadline=False)
        return self

    def native_request(self):
        values = self.model_dump(mode="json", exclude={"gpus"})
        return {"version": 1, **values, "device_count": len(self.gpus)}


def start_qualification(manager, body, *, python, runtime, models, hardware):
    """Configuration paths are trusted internal arguments, never API fields."""
    if os.environ.get("AI_STATION_REAL_GPU_TESTS") != "1":
        raise ValueError("Whole-recording qualification requires an explicit real-GPU opt-in")
    return _start_owned(manager, body, python=python, runtime=runtime, models=models, hardware=hardware)


def _start_owned(manager, body, *, python, runtime, models, hardware, verify_installation=True):
    """Only qualification or the configured typed native adapter may call this."""
    checked_request(body.native_request(), check_deadline=False)
    python = Path(python).expanduser().absolute()  # Preserve the venv executable symlink.
    runtime, models = Path(runtime).expanduser().resolve(), Path(models).expanduser().resolve()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Configured Sonic Python is unavailable")
    root = manager.data_dir.resolve()
    managed = None
    if body.recipe.get("environment_id"):
        from ai_station_runner.avatar_environment import resolve_id

        managed = resolve_id(root, body.recipe["environment_id"])
        if (
            python != managed["sonic_python"]
            or runtime != managed["sonic_dir"]
            or models != managed["sonic_models"]
        ):
            raise ValueError("Avatar launch must use its exact frozen environment")
    run_id = str(body.run_id)
    launch = resolve_child(root, f"runs/{run_id}/whole-avatar-launch")
    if launch != root / f"runs/{run_id}/whole-avatar-launch":
        raise ValueError("Whole-recording launch work must not contain symlinks")
    record = {
        "request": body.model_dump(mode="json"),
        "python": str(python),
        "runtime": str(runtime),
        "models": str(models),
    }
    receipt = launch / "launch.json"
    config = launch / "request.json"
    if launch.exists():
        if (
            receipt.resolve() != receipt
            or not receipt.is_file()
            or json.loads(receipt.read_text()) != record
            or config.resolve() != config
            or not config.is_file()
            or json.loads(config.read_text()) != body.native_request()
        ):
            raise ValueError("Whole-recording launch identity changed; inspect existing work")
        try:
            owned = manager.inspect(run_id)
        except ProcessNotOwned as exc:
            raise ValueError("Inspect whole-recording launch work before retrying") from exc
        if owned.get("executor") != "sonic_whole":
            raise ValueError("Existing whole-recording Run belongs to another executor")
        return owned
    try:
        manager.inspect(run_id)
    except ProcessNotOwned:
        pass
    else:
        raise ValueError("Inspect existing owned process before creating whole-recording work")
    checked_request(body.native_request())
    # Hash before creating any work or starting an owned process. Native entry
    # independently rechecks source, weights, input bytes and frozen dimensions.
    if verify_installation and installation_observation(runtime, models) != body.recipe["observation"]:
        raise ValueError("Sonic implementation or model observation changed")
    if inspect_inputs(root, body.portrait.model_dump(), body.audio.model_dump()) != body.observed_input:
        raise ValueError("Frozen portrait geometry or canonical PCM changed")
    devices = {str(gpu["index"]): gpu for gpu in hardware.get("gpus", [])}
    selected = []
    for index in body.gpus:
        gpu = devices.get(str(index))
        if not gpu or not isinstance(gpu.get("uuid"), str) or not gpu["uuid"].startswith("GPU-"):
            raise ValueError("An allocated whole-recording GPU is no longer present")
        selected.append(gpu["uuid"])
    if len(set(selected)) != len(selected):
        raise ValueError("Allocated GPU identities must be distinct")
    output = resolve_child(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4")
    if (
        output != root / f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4"
        or output.exists()
        or output.with_suffix(".json").exists()
    ):
        raise ValueError("Inspect existing or changed whole-recording output")
    if managed:
        from ai_station_runner.avatar_prepare import driver_supported

        if not driver_supported("580.126.20") or any(
            (devices[str(i)].get("memory_total_mib") or 0) < 12288 for i in body.gpus
        ):
            raise ValueError("The allocated avatar GPU or driver does not fit its prepared profile")
    prefix = scope_prefix(run_id, 18432)
    launch.mkdir(parents=True, mode=0o700)
    receipt.write_text(json.dumps(record, sort_keys=True))
    receipt.chmod(0o600)
    config.write_text(json.dumps(body.native_request(), sort_keys=True))
    config.chmod(0o600)
    environment = {
        key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "LD_LIBRARY_PATH"}
    }
    environment.update(
        **scope_environment(),
        AI_STATION_REAL_GPU_TESTS="1",
        PYTHONPATH=str(Path(__file__).resolve().parent.parent),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        CUDA_VISIBLE_DEVICES=",".join(selected),
        USE_TF="0",
        USE_FLAX="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TMPDIR=str(launch),
        NUMBA_CACHE_DIR=str(launch / "numba"),
        TORCHINDUCTOR_CACHE_DIR=str(launch / "torch"),
        XDG_CACHE_HOME=str(launch / "cache"),
    )
    if managed:
        home = launch / "home"
        home.mkdir(mode=0o700)
        environment.pop("LD_LIBRARY_PATH", None)
        environment.update(PATH=str(managed["environment"] / "bin") + ":/usr/bin:/bin", HOME=str(home))
    return manager.start(
        run_id=run_id,
        argv=[
            *prefix,
            str(python),
            str(Path(__file__).with_name("sonic_entry.py")),
            "--runtime-dir",
            str(runtime),
            "--model-dir",
            str(models),
            "--data-root",
            str(root),
            "--request",
            str(config),
        ],
        cwd=launch,
        executor="sonic_whole",
        env=environment,
        deadline_at=body.deadline_at,
    )
