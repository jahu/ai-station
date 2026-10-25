"""Typed GPU-only Krea dispatch through the existing owned process manager."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.avatars import owned
from ai_station_runner.config import get_settings
from ai_station_runner.krea2 import KreaFile, KreaOptions
from ai_station_runner.media_compose import verified_path
from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.security import PathBoundaryError, ensure_within
from ai_station_runner.telemetry import collect

REVISIONS = {
    "comfy": "19ae172bff6c9e4c738e7f2e00fe087f5b5b46ab",
    "gguf": "6ea2651e7df66d7585f6ffee804b20e92fb38b8a",
    "edit": "13ef60f20828949becada815d3cbc371eb5ccaab",
}


class KreaRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    options: KreaOptions
    model_file: KreaFile
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    gpus: list[StrictInt] = Field(min_length=1, max_length=2)
    inputs: list[MediaInput] = Field(default_factory=list, max_length=2)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def valid(self) -> Self:
        if len(set(self.gpus)) != len(self.gpus) or any(gpu < 0 for gpu in self.gpus):
            raise ValueError("Krea requires distinct discovered GPU indexes")
        self.options.validate_references(len(self.inputs))
        if any(source.size_bytes > 20 * 1024**2 for source in self.inputs):
            raise ValueError("Krea reference exceeds the image upload limit")
        return self


def _model_path(path):
    settings = get_settings()
    roots = [Path(value) for value in settings.model_roots.split(":") if value.strip()]
    try:
        result = ensure_within(Path(path), roots)
    except PathBoundaryError as exc:
        raise HTTPException(403, "Krea weight is outside configured model roots") from exc
    if str(result) != path or not result.is_file():
        raise HTTPException(422, "Krea requires an existing canonical model file")
    return result


def profile():
    settings = get_settings()
    if not settings.krea_enabled or not settings.krea_runtime_dir or not settings.krea_companions_dir:
        raise HTTPException(409, "The qualified Krea image runtime is not enabled")
    root = Path(settings.krea_runtime_dir).expanduser().absolute()
    data = settings.host_data_dir().resolve()
    if (
        root.resolve() != root
        or root == data
        or data in root.parents
        or not root.is_dir()
        or root.stat().st_uid != os.getuid()
        or root.stat().st_mode & 0o022
    ):
        raise HTTPException(409, "Krea runtime must be private native code outside application storage")
    try:
        receipt = json.loads((root / "ai-station-runtime.json").read_text())
        if receipt["owner"] != "ai-station" or receipt["profile"] != "gpu-only":
            raise ValueError("Invalid runtime owner")
        for name, revision in REVISIONS.items():
            source = root / name
            if (
                source.resolve() != source
                or receipt["sources"][name]["revision"] != revision
                or (source / ".git/HEAD").read_text().strip() != revision
            ):
                raise ValueError("Unqualified runtime source")
        python = root / "venv/bin/python"
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ValueError("Missing runtime Python")
        companion = Path(settings.krea_companions_dir).expanduser().resolve()
        weights = json.loads((companion / "ai-station-model.json").read_text())
        files = {}
        roles = {
            "text_encoders/qwen3vl_4b_fp8_scaled.safetensors": "encoder",
            "vae/qwen_image_vae.safetensors": "vae",
            "loras/krea2_general_edit_v2_r64.safetensors": "general",
            "loras/krea2_identity_edit_v2_r64.safetensors": "identity",
        }
        for item in weights["files"]:
            role = roles[item["path"]]
            path = _model_path(str(companion / item["path"]))
            if path.stat().st_size != item["size"]:
                raise ValueError("Changed companion file")
            files[role] = KreaFile(path=str(path), size=item["size"], sha256=item["sha256"])
        if set(files) != set(roles.values()):
            raise ValueError("Incomplete companion installation")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "Krea runtime or companion installation is incomplete") from exc
    return root, python, files


def capabilities():
    try:
        runtime, _python, files = profile()
        return {
            "available": True,
            "backend": "krea2",
            "modes": ["t2i", "img2img", "recompose"],
            "maximum_references": 2,
            "cpu_offload": False,
            "gpu_profiles": [1, 2],
            "profile_sha256": profile_sha256(runtime, files),
        }
    except HTTPException as exc:
        return {"available": False, "backend": "krea2", "reason": exc.detail, "cpu_offload": False}


def profile_sha256(runtime, files):
    frozen = {
        "runtime": str(runtime),
        "revisions": REVISIONS,
        "files": {role: file.model_dump() for role, file in files.items()},
    }
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def start(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Krea read/write permissions are required")
    runtime, python, files = profile()
    if body.profile_sha256 != profile_sha256(runtime, files):
        raise HTTPException(409, "Krea runtime or companions changed after this job was prepared")
    model = _model_path(body.model_file.path)
    if model.suffix not in {".gguf", ".safetensors"} or model.stat().st_size != body.model_file.size:
        raise HTTPException(422, "Krea checkpoint changed or has an unsupported format")
    root = get_settings().host_data_dir().resolve()
    discovered = {int(gpu["index"]): gpu.get("uuid", "") for gpu in collect(root).get("gpus", [])}
    if not set(body.gpus).issubset(discovered) or any(
        not re.fullmatch(r"GPU-[a-fA-F0-9-]+", discovered[gpu]) for gpu in body.gpus
    ):
        raise HTTPException(422, "Krea GPU allocation was not discovered")
    inputs = []
    for observation in body.inputs:
        path = verified_path(root, observation)
        if not observation.relative_path.startswith("artifacts/"):
            raise HTTPException(403, "Krea references must be app-owned artifacts")
        try:
            with Image.open(path) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 64 * 1024**2:
                    raise ValueError("Unsupported reference")
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "Krea reference is not a bounded image") from exc
        inputs.append({"path": str(path), "size": observation.size_bytes, "sha256": observation.sha256})
    role = body.options.lora_role()
    selected = {name: file.model_dump() for name, file in files.items() if name in {"encoder", "vae", role}}
    selected["model"] = body.model_file.model_dump()
    run_id = str(body.run_id)
    work = root / "runs" / run_id / "krea2"
    if work.resolve() != work:
        raise HTTPException(403, "Krea work directory must not contain symlinks")
    output = owned(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.png")
    if work.exists() or output.exists():
        raise HTTPException(409, "Inspect existing Krea work before retrying")
    work.mkdir(parents=True, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True)
    config = work / "request.json"
    with config.open("x") as handle:
        json.dump(
            {
                "request": body.options.model_dump(),
                "files": selected,
                "inputs": inputs,
                "runtime": {name: str(runtime / name) for name in REVISIONS},
                "gpu_count": len(body.gpus),
                "work": str(work),
                "output": str(output),
            },
            handle,
        )
    config.chmod(0o600)
    environment = {
        key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "LD_LIBRARY_PATH"}
    }
    environment.update(
        PYTHONPATH=str(Path(__file__).resolve().parent.parent),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        CUDA_VISIBLE_DEVICES=",".join(discovered[gpu] for gpu in body.gpus),
        HF_HOME=str(work / "cache"),
        XDG_CACHE_HOME=str(work / "cache"),
        TORCH_HOME=str(work / "cache/torch"),
        TRITON_CACHE_DIR=str(work / "cache/triton"),
        TMPDIR=str(work),
    )
    return manager.start(
        run_id=run_id,
        argv=[str(python), "-m", "ai_station_runner.krea2_job", str(config)],
        cwd=work,
        executor="photo_pipe",
        env=environment,
        **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
    )
