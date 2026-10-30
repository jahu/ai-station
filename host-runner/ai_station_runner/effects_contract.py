"""Frozen offline MMAudio profile; request validation does not import models."""

import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.security import resolve_child

PROFILE = "mmaudio_large44_bf16_v1"
RAM_MIB = 18432
VRAM_MIB = 8192
SOURCE_SHA256 = "9714169157a314fcf002b030e2a77c6b0f422088b47f5dc9e492931638a0886b"
ASSETS = {
    "clip/open_clip_config.json": {
        "size": 735,
        "sha256": "e043bd1129b97d3afc77eef2e8bfda940af588dabf2cbaacc21e956345402f67",
    },
    "clip/open_clip_pytorch_model.bin": {
        "size": 3947081637,
        "sha256": "c07a17b547d461c60a3cce5062b26bf8545b13de602c4c59d8490361eb716033",
    },
    "flow.pth": {
        "size": 4122474715,
        "sha256": "a6bf693424fbd4ce0244fff8c412347714d5ac586e28dbeffadfa0f2b647af74",
    },
    "sync.pth": {
        "size": 950058171,
        "sha256": "8aff082f2df5c3bc52759db0c865c7ee772ae6400b860d1b7e90413f2defb67c",
    },
    "vae.pth": {
        "size": 1221942998,
        "sha256": "ab6cc15dc31947675f75c950c41f4dcfd0d6d1817555ac871f809ec388e4651a",
    },
    "vocoder/bigvgan_generator.pt": {
        "size": 489041291,
        "sha256": "d9fe7ec6bd0b44ed9d66973d5012d8181c1570b01e5c72df51973e241dccd357",
    },
    "vocoder/config.json": {
        "size": 1403,
        "sha256": "65b7f487bfaf15256056a75f6667ef5f640214c981922a111927873705ea4ddb",
    },
}
WRAPPERS = (
    "effects_contract.py",
    "effects_job.py",
    "effects_timing.py",
    "effects_video.py",
    "memory_scope.py",
    "media_inputs.py",
    "security.py",
)


class VideoInput(MediaInput):
    frames: StrictInt = Field(ge=1, le=7500)
    fps: Literal[24, 25]
    width: StrictInt = Field(ge=128, le=1280, multiple_of=32)
    height: StrictInt = Field(ge=128, le=1280, multiple_of=32)

    @model_validator(mode="after")
    def bounded(self):
        if self.frames > self.fps * 300 or self.width * self.height > 1280 * 704:
            raise ValueError("Video exceeds the bounded effects profile")
        return self


class EffectsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    video: VideoInput
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    steps: StrictInt = Field(default=25, ge=10, le=50)
    cfg: float = Field(default=4.5, ge=1, le=10, strict=True, allow_inf_nan=False)
    seed: StrictInt = Field(default=42, ge=0, le=2147483647)
    gpu: StrictInt = Field(ge=0)
    observation: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: float = Field(gt=0, strict=True, allow_inf_nan=False)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def direct(root, relative):
    root = Path(root)
    p = resolve_child(root, relative)
    if p != root / relative or not p.is_file():
        raise ValueError("Effects files must be direct configured files")
    return p


def source_files(runtime):
    root = Path(runtime) / "mmaudio"
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Effects source contains symlinks")
    files = sorted(p for p in root.rglob("*") if p.suffix in (".py", ".yaml", ".json"))
    if not files or len(files) > 1000:
        raise ValueError("Invalid effects source tree")
    return [direct(runtime, p.relative_to(runtime).as_posix()) for p in files]


def files(runtime, models):
    return [
        *source_files(runtime),
        *(direct(models, n) for n in ASSETS),
        *(direct(Path(__file__).parent, n) for n in WRAPPERS),
    ]


def installation_signature(runtime, models):
    return tuple(
        (str(p), p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
        for p in files(runtime, models)
    )


def installation_observation(runtime, models):
    h = hashlib.sha256()
    for p in source_files(runtime):
        name = p.relative_to(runtime).as_posix().encode()
        h.update(len(name).to_bytes(4, "big"))
        h.update(name)
        h.update(bytes.fromhex(digest(p)))
    if h.hexdigest() != SOURCE_SHA256:
        raise ValueError("MMAudio source differs from the qualified revision")
    for name, expected in ASSETS.items():
        p = direct(models, name)
        if p.stat().st_size != expected["size"] or digest(p) != expected["sha256"]:
            raise ValueError("Effects model differs from publisher files")
    return hashlib.sha256(
        json.dumps(
            {
                "profile": PROFILE,
                "source": SOURCE_SHA256,
                "assets": ASSETS,
                "wrappers": {n: digest(direct(Path(__file__).parent, n)) for n in WRAPPERS},
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def video_path(root, source, *, verify=True):
    if not source.relative_path.startswith("artifacts/") or not source.relative_path.endswith(".mp4"):
        raise ValueError("Choose an owned MP4 artifact")
    path = direct(root, source.relative_path)
    if path.stat().st_size != source.size_bytes or verify and digest(path) != source.sha256:
        raise ValueError("Effects source video changed")
    return path
