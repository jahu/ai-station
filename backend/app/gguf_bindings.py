"""Portable complete owned language-model bindings, without native imports."""

import math

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import select

from app.model_setup import fingerprint
from app.models import ModelDefinition


class OwnedPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=256 * 1024**3)
    mtime: float = Field(gt=0, allow_inf_nan=False)


class OwnedBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    parts: tuple[OwnedPart, ...] = Field(min_length=2, max_length=64)

    @model_validator(mode="after")
    def closed(self):
        if len({p.sha256 for p in self.parts}) != len(self.parts) or self.size_bytes > 2 * 1024**4:
            raise ValueError("Choose a bounded complete set of distinct owned GGUF objects")
        return self

    @property
    def size_bytes(self):
        return sum(p.size_bytes for p in self.parts)


def checked_proof(bundle, proof):
    if (
        not isinstance(proof, dict)
        or proof.get("kind") != "gguf_split"
        or proof.get("bundle_id") != fingerprint(bundle.model_dump(mode="json"))
        or proof.get("part_count") != len(bundle.parts)
        or proof.get("size_bytes") != bundle.size_bytes
        or proof.get("structurally_verified") is not True
    ):
        raise ValueError("The complete native GGUF proof differs from its frozen object set")
    return proof


def binding_of(session, model):
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == model.id))
    metadata = definition.metadata_json if definition else {}
    raw = metadata.get("model_bundle")
    if raw is None:
        return None
    bundle = OwnedBundle.model_validate(raw)
    first = bundle.parts[0]
    if (
        model.host_path is not None
        or model.relative_path != "models/store/" + first.sha256
        or (model.sha256, model.size_bytes, model.mtime) != (first.sha256, first.size_bytes, first.mtime)
    ):
        raise ValueError("The primary GGUF registry observation differs from its complete binding")
    checked_proof(bundle, metadata.get("bundle_proof"))
    return bundle.model_dump(mode="json")


def size_of(session, model):
    bundle = binding_of(session, model)
    return sum(p["size_bytes"] for p in bundle["parts"]) if bundle else model.size_bytes


def fitted_context(proof, gpu_memory_mib, ceiling):
    context = proof["context_profile"]
    if not gpu_memory_mib or any(
        type(value) not in {int, float} or not math.isfinite(value) or value <= 0 for value in gpu_memory_mib
    ):
        raise ValueError("Inspect each selected GPU before choosing a bundle context")
    count = len(gpu_memory_mib)
    weights = (proof["size_bytes"] + count - 1) // count
    fixed = weights + proof["largest_layer_bytes"] + proof["shared_tensor_bytes"]
    # The native loader charges the full Q8 cache on each device. Do not pool
    # unequal VRAM capacities or divide KV memory by the number of GPUs here.
    available = min(gpu_memory_mib) * 1024**2 - fixed - (context["state_reserve_mib"] + 1024) * 1024**2
    tokens = int(available // context["q8_kv_bytes_per_token"])
    return min(tokens, ceiling, context["trained_context"]) // 256 * 256


def definition_proof(session, model):
    if binding_of(session, model) is None:
        return None
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == model.id))
    return definition.metadata_json["bundle_proof"]


def transfer_files(entry):
    return (
        tuple(part.file for part in entry.parts)
        if getattr(entry, "origin", None) == "hub_split"
        else (entry.file,)
    )


def candidate_size(entry):
    return getattr(entry, "total_size_bytes", entry.file.size_bytes)
