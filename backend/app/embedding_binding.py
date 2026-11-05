"""Finite, app-owned encoder/tokenizer coordinates shared with offline CPU children."""

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.embedding_graph import MAX_MODEL_BYTES, PROFILE, recipe


class Object(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=MAX_MODEL_BYTES)
    mtime: float = Field(ge=0, allow_inf_nan=False)


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["e5-small-onnx-f32-v1"] = PROFILE
    model: Object
    tokenizer: Object
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def fixed_companion(self):
        expected = recipe(self.profile)
        if self.schema_sha256 != expected["schema_sha256"] or any(
            getattr(self.tokenizer, key) != expected["tokenizer"][key] for key in ("sha256", "size_bytes")
        ):
            raise ValueError("This encoder requires its exact reviewed graph and tokenizer")
        return self


def objects(root, binding, *, rehash=False):
    value = Binding.model_validate(binding)
    root = Path(root).resolve(strict=True)
    paths = {}
    for role in ("model", "tokenizer"):
        source = getattr(value, role)
        path = root / "models/store" / source.sha256
        if path.resolve(strict=True) != path:
            raise ValueError("Encoder objects cannot cross symlinks")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or before.st_mode & 0o222
                or before.st_size != source.size_bytes
                or abs(before.st_mtime - source.mtime) > 0.001
            ):
                raise ValueError("The immutable encoder bundle changed")
            if rehash and hashlib.file_digest(handle, "sha256").hexdigest() != source.sha256:
                raise ValueError("The encoder bundle content changed")
            after = path.stat()
            if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (
                after.st_dev,
                after.st_ino,
                after.st_mtime_ns,
                after.st_size,
            ):
                raise ValueError("The encoder object changed during verification")
        paths[role] = path
    return value, paths


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    deadline_at: float = Field(gt=0, allow_inf_nan=False)
    binding: Binding


def read_job(root, path):
    root, path = Path(root).resolve(strict=True), Path(path)
    if (
        path.resolve(strict=True) != path
        or path.name != "embedding-model.json"
        or path.parent.parent != root / "runs"
    ):
        raise ValueError("The encoder needs its owned Run configuration")
    info = path.stat()
    if (
        info.st_size > 8192
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o022
    ):
        raise ValueError("Encoder configuration exceeds its bound")
    job = Job.model_validate(json.loads(path.read_text()))
    if path.parent.name != str(job.run_id):
        raise ValueError("Encoder configuration belongs to another Run")
    return job
