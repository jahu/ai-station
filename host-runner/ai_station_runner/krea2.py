"""Fixed Krea image invocation contract; no caller-provided graph or code."""

import hashlib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KreaOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["t2i", "img2img", "recompose"]
    prompt: str = Field(min_length=1, max_length=10_000)
    negative: str = Field(default="", max_length=10_000)
    width: int = Field(default=768, ge=256, le=2048, multiple_of=32)
    height: int = Field(default=1024, ge=256, le=2048, multiple_of=32)
    steps: int = Field(default=8, ge=1, le=100)
    cfg: float = Field(default=1, ge=1, le=10, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0, le=4294967295)
    reference_strength: float | None = Field(default=None, ge=0, le=8, allow_inf_nan=False)
    reference_layout: Literal["aligned", "beside"] = "aligned"
    grounding_px: int = Field(default=768, ge=384, le=1024, multiple_of=64)

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.width * self.height > 2_097_152:
            raise ValueError("Krea output must be at most two megapixels")
        if self.mode == "t2i" and (self.reference_strength is not None or self.reference_layout != "aligned"):
            raise ValueError("Reference settings require Edit or Recompose")
        if self.mode != "t2i" and self.reference_strength is None:
            self.reference_strength = 4 if self.mode == "img2img" else 2
        return self

    def validate_references(self, count):
        expected = {"t2i": (0,), "img2img": (1,), "recompose": (1, 2)}[self.mode]
        if count not in expected:
            raise ValueError(f"Krea {self.mode} requires reference count in {expected}")

    def lora_role(self):
        return {"t2i": None, "img2img": "general", "recompose": "identity"}[self.mode]


class KreaFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    size: int = Field(gt=0, le=32 * 1024**3)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    def verify(self):
        path = Path(self.path)
        if not path.is_absolute() or not path.is_file() or path.stat().st_size != self.size:
            raise ValueError("Krea model file is missing or its size changed")
        # Runtime receives only canonical snapshots resolved by the native API.
        if path.resolve() != path:
            raise ValueError("Krea model snapshot is not canonical")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != self.sha256:
            raise ValueError("Krea model file failed SHA-256 verification")
        return path


def gpu_only_args(work):
    return [
        "ai-station-krea2",
        "--gpu-only",
        "--disable-dynamic-vram",
        "--disable-async-offload",
        "--cache-none",
        "--disable-all-custom-nodes",
        "--disable-api-nodes",
        "--offline",
        "--base-directory",
        str(work),
    ]


def require_gpu_placement(patcher, expected):
    """Fail rather than silently accept CPU offload from a changed runtime/plugin."""
    for attribute in ("load_device", "offload_device"):
        actual = getattr(patcher, attribute, None)
        if actual is None or str(actual) != f"cuda:{expected}":
            raise ValueError(f"Krea GPU-only placement rejected {attribute}={actual}")
