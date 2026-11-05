"""Frozen complete publisher GGUF sets; no filename-based runtime authority."""

import re
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.hub_candidates import HubCandidate, LanguageProfile
from app.hub_model_parts import annotate, coordinate, for_file
from app.model_download_files import FileSpec
from app.model_setup import fingerprint
from app.model_source_recovery import source_identity

INSTALLATION_QUALIFIED = False


class PublisherPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str = Field(min_length=1, max_length=400)
    file: FileSpec


class HubSplitCandidate(HubCandidate):
    origin: Literal["hub_split"] = "hub_split"
    parts: tuple[PublisherPart, ...] = Field(min_length=2, max_length=64)

    def expected_id(self):
        return "hub-bundle-" + fingerprint([p.model_dump(mode="json") for p in self.parts])[:24]

    @property
    def total_size_bytes(self):
        return sum(part.file.size_bytes for part in self.parts)

    @model_validator(mode="after")
    def complete_coordinate(self):
        first = self.parts[0]
        if (self.file, self.filename) != (first.file, first.filename):
            raise ValueError("A complete model must use its first physical part as the primary object")
        group = coordinate(first.filename)
        if not group or group[2] != len(self.parts) or self.total_size_bytes > 2 * 1024**4:
            raise ValueError("The complete GGUF group exceeds its supported bounds")
        if len({p.file.sha256 for p in self.parts}) != len(self.parts):
            raise ValueError("GGUF parts require distinct object identities")
        for index, part in enumerate(self.parts, 1):
            if coordinate(part.filename) != (group[0], index, len(self.parts)):
                raise ValueError("GGUF part names must form one ordered complete set")
            if len(part.file.urls) != 1 or source_identity(part.file.urls[0]) != (
                self.repository,
                self.revision,
                part.filename,
            ):
                raise ValueError("Every GGUF part must belong to the same pinned publisher source")
        return self


def candidate_from_profile(observation, filename, profile, *, context_ceiling=32768):
    profile = LanguageProfile.model_validate(profile)
    if (profile.source_repository, profile.source_revision) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The publisher profile belongs to another immutable source")
    if observation.get("pipeline_hint", "") not in {"", "text-generation"} or re.search(
        r"mmproj|projector", filename, re.I
    ):
        raise ValueError("This complete bundle needs a supported language-model profile")
    selected = next((f for f in observation["files"] if f["filename"] == filename), None)
    group = for_file(observation, selected or {})
    if not group or group.get("status") != "complete_metadata":
        raise ValueError("Inspect all GGUF parts and their publisher identities first")
    rows = [{**part, "identity_available": True} for part in group["parts"]]
    rebuilt = annotate(rows)
    if len(rebuilt) != 1 or rebuilt[0] != group:
        raise ValueError("The complete publisher group does not match its immutable observation")
    if type(context_ceiling) is not int or context_ceiling not in {32768, 131072}:
        raise ValueError("Choose a supported context target")
    parts = tuple(
        PublisherPart(
            filename=part["filename"],
            file=FileSpec(
                sha256=part["sha256"],
                size_bytes=part["size_bytes"],
                urls=(
                    f"https://huggingface.co/{observation['repository']}/resolve/{observation['revision']}/{quote(part['filename'], safe='/')}",
                ),
            ),
        )
        for part in group["parts"]
    )
    quant = re.search(r"(?:^|[.-])((?:I?Q|BF|F)[0-9][A-Z0-9_]*)(?=\.gguf$)", group["name"], re.I)
    return HubSplitCandidate(
        id="hub-bundle-" + fingerprint([p.model_dump(mode="json") for p in parts])[:24],
        name=observation["repository"].rsplit("/", 1)[-1][:180],
        filename=parts[0].filename,
        file=parts[0].file,
        parts=parts,
        quantization=quant.group(1).upper() if quant else "GGUF",
        repository=observation["repository"],
        revision=observation["revision"],
        license=observation["license"],
        source_url=observation["source_url"],
        license_url=observation["license_url"],
        context_ceiling=min(context_ceiling, profile.trained_context // 256 * 256),
        **profile.model_dump(exclude={"source_repository", "source_revision"}),
    )


def recommendation(entry, hardware, proof=None):
    import math

    from app.gguf_bindings import fitted_context

    denied = {
        "fits": False,
        "reason": "Inspect compatible CUDA GPUs and sufficient host RAM for the complete model",
        "gpus": [],
        "context_size": None,
    }
    if (hardware.get("host") or {}).get("system") == "Darwin" or hardware.get("container_gpu_ready") is False:
        return denied
    ram = (hardware.get("memory") or {}).get("total_mib")
    required_ram = math.ceil(entry.total_size_bytes * 1.15 / 1024**2) + 1024
    if type(ram) not in {int, float} or not math.isfinite(ram) or ram < required_ram:
        return {**denied, "reason": "More host RAM is needed to load the complete model"}
    devices = [
        g
        for g in hardware.get("gpus", [])
        if type(g.get("index")) is int
        and type(g.get("memory_total_mib")) in {int, float}
        and math.isfinite(g["memory_total_mib"])
        and 0 < g["memory_total_mib"] < 1048576
    ]
    devices.sort(key=lambda g: (-g["memory_total_mib"], g["index"]))
    if len(devices) > 16 or len({g["index"] for g in devices}) != len(devices):
        return denied
    estimate = proof or {
        "size_bytes": entry.total_size_bytes,
        # Pre-download placement is an estimate from publisher geometry. Exact
        # largest-layer/shared tensor bytes replace it after native verification.
        "largest_layer_bytes": math.ceil(entry.total_size_bytes * 2 / entry.attention_layers),
        "shared_tensor_bytes": math.ceil(entry.total_size_bytes / 10),
        "context_profile": {
            "trained_context": entry.trained_context,
            "state_reserve_mib": entry.state_reserve_mib,
            "q8_kv_bytes_per_token": entry.attention_layers
            * entry.kv_heads
            * ((entry.key_length + entry.value_length) // 32)
            * 34,
        },
    }
    best = None
    for count in range(1, len(devices) + 1):
        group = devices[:count]
        context = fitted_context(estimate, [g["memory_total_mib"] for g in group], entry.context_ceiling)
        if context < 4096:
            continue
        value = {
            "fits": True,
            "reason": "Estimated whole-model fit on each GPU; native tensor placement is checked after download"
            if proof is None
            else "Complete native tensor and context geometry fits each selected GPU",
            "gpus": [g["index"] for g in group],
            "context_size": context,
            "cache_type": "q8_0",
        }
        if best is None or value["context_size"] > best["context_size"]:
            best = value
        if context >= entry.context_ceiling:
            break
    return best or {
        **denied,
        "reason": "The complete weights and useful context do not fit each selected GPU",
    }


def assessment(entry, hardware, storage):
    from app.model_hardware import number

    free = number((storage or {}).get("free_bytes"))
    headroom = number((storage or {}).get("headroom_bytes"))
    choice = recommendation(entry, hardware)
    return {
        "disk": {
            "status": "unknown"
            if free is None or headroom is None
            else "file_fits"
            if free >= entry.total_size_bytes + headroom
            else "insufficient",
            "file_bytes": entry.file.size_bytes,
            "model_bundle_bytes": entry.total_size_bytes,
            "free_bytes": free,
            "headroom_bytes": headroom,
            "complete_install_budget_known": False,
            "note": "Every part is included; runtime image and staging may need separate space.",
        },
        "runtime_status": "supported_complete_bundle_plan",
        "hardware_status": "estimated_fit" if choice["fits"] else "insufficient",
        "profiles": [
            {
                "catalog_id": entry.id,
                "name": entry.name,
                "capability": "chat",
                "runtime": "llama.cpp",
                "quantization": entry.quantization,
                "fit": "estimated_fit" if choice["fits"] else "insufficient",
                "recommendation": choice,
                "locally_qualified": False,
                "provenance": "pinned_publisher_configuration_and_complete_part_set",
            }
        ],
        "reason": choice["reason"],
        "automatic_ram_offload": False,
        "automatic_cloud_fallback": False,
    }
