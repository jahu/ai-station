"""Pinned Wan checkpoints compose with the existing offline video preparation."""

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.hub_checkpoint_headers import inspect as inspect_header
from app.hub_sources import parse_source
from app.model_download_files import FileSpec
from app.model_setup import fingerprint
from app.model_source_recovery import source_identity
from app.video_setup_client import VideoSetupClient

PROFILE = "wan22-5b-linux-x86-64-python312-v1"
SLOT = "wan22-5b-diffusion-v1"


class HubVideoCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: Literal["hub_video"] = "hub_video"
    id: str
    name: str = Field(min_length=1, max_length=180)
    capability: Literal["video"] = "video"
    runtime: Literal["wan-comfy-headless"] = "wan-comfy-headless"
    runtime_profile: None = None
    architecture: Literal["wan22_5b"] = "wan22_5b"
    quantization: Literal["F16"] = "F16"
    filename: str = Field(min_length=1, max_length=400)
    file: FileSpec
    repository: str
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_url: str
    license: str = Field(min_length=1, max_length=120)
    license_url: str
    configuration_repository: str
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration_filename: Literal["safetensors-header"]
    config_url: str
    checkpoint_header: dict
    slot: dict
    setup_recipe: dict
    setup_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prepare_engine: StrictBool
    preparation_available: StrictBool
    host_profile_compatible: StrictBool
    prerequisite_budget_bytes: StrictInt = Field(ge=0)
    preparation_notice: str = Field(default="", max_length=500)
    component_licenses: list[dict] = Field(max_length=12)

    @model_validator(mode="after")
    def valid(self):
        if (
            self.id != "hub-video-" + self.file.sha256[:24]
            or len(self.file.urls) != 1
            or source_identity(self.file.urls[0]) != (self.repository, self.revision, self.filename)
            or parse_source(self.configuration_repository).repository != self.configuration_repository
            or self.source_url != f"https://huggingface.co/{self.repository}/tree/{self.revision}"
            or self.license_url != f"https://huggingface.co/{self.repository}/blob/{self.revision}/README.md"
            or self.config_url != self.file.urls[0]
            or self.configuration_repository != self.repository
            or self.configuration_revision != self.revision
            or self.configuration_sha256 != self.checkpoint_header.get("header_sha256")
            or self.checkpoint_header.get("schema_sha256") != self.slot.get("schema_sha256")
            or self.checkpoint_header.get("tensor_count") != self.slot.get("tensor_count")
            or not self.checkpoint_header.get("dtypes")
            or any(v not in self.slot.get("allowed_dtypes", []) for v in self.checkpoint_header["dtypes"])
            or self.slot.get("profile") != SLOT
            or self.slot.get("runtime_profile") != PROFILE
            or self.slot.get("role") != "wan_model"
            or self.setup_recipe.get("profile") != PROFILE
            or self.slot.get("runtime_manifest_sha256") != self.setup_manifest_sha256
            or fingerprint(self.setup_recipe) != self.setup_manifest_sha256
            or {v.get("role") for v in self.setup_recipe.get("inputs", []) if v.get("kind") == "model"}
            != {"wan_model", "wan_text_encoder", "wan_vae"}
        ):
            raise ValueError("The video checkpoint needs its pinned source and complete fixed runtime recipe")
        return self


def readiness(report):
    ready = (report.get("managed_video") or {}).get("available") is True
    required = (report.get("storage") or {}).get("required_bytes")
    if type(required) is not int or required < 0:
        required = sum(v["size_bytes"] for v in report["recipe"]["inputs"]) + 12 * 1024**3
    return {
        "prepare_engine": not ready,
        "preparation_available": ready or report.get("installation_available") is True,
        "host_profile_compatible": (report.get("recommendation") or {}).get("fits") is True,
        "preparation_notice": (report.get("installation_notice") or "")[:500],
        "prerequisite_budget_bytes": 0 if ready else required,
    }


async def resolve_profile(observation, check, filename=None):
    matches = [
        f
        for f in observation["files"]
        if f.get("format") == "safetensors"
        and f.get("identity_available")
        and (filename is None or f["filename"] == filename)
    ]
    if len(matches) != 1:
        raise ValueError("Choose a specific complete checkpoint file to inspect its actual graph")
    file = matches[0]
    check()
    report = VideoSetupClient(timeout=20).runtime_setup_catalog()
    check()
    slots = [v for v in report.get("checkpoint_slots", []) if v.get("profile") == SLOT]
    if len(slots) != 1:
        raise ValueError("Update the Host Runner to inspect compatible video checkpoint slots")
    slot = slots[0]
    header = await inspect_header(file, check)
    if (
        header["tensor_count"] != slot["tensor_count"]
        or header["schema_sha256"] != slot["schema_sha256"]
        or any(v not in slot["allowed_dtypes"] for v in header["dtypes"])
    ):
        raise ValueError("This checkpoint graph or precision needs its own compatible runtime slot")
    return {
        "source_repository": observation["repository"],
        "source_revision": observation["revision"],
        "source_filename": file["filename"],
        "source_sha256": file["sha256"],
        "configuration_repository": observation["repository"],
        "configuration_revision": observation["revision"],
        "configuration_sha256": header["header_sha256"],
        "configuration_filename": "safetensors-header",
        "config_url": file["source_url"],
        "checkpoint_header": header,
        "slot": slot,
        "component_licenses": report.get("licenses", []),
        "setup_recipe": report["recipe"],
        "setup_manifest_sha256": report["manifest_sha256"],
        **readiness(report),
    }


def candidate_from_profile(observation, filename):
    profile = dict(observation["video_profile"])
    if (profile.pop("source_repository"), profile.pop("source_revision")) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The video profile belongs to another immutable source")
    matches = [v for v in observation["files"] if v["filename"] == filename]
    if (
        len(matches) != 1
        or not matches[0].get("identity_available")
        or matches[0].get("format") != "safetensors"
        or re.search(r"lora|adapter|vae|encoder|\d{5}-of-\d{5}\.safetensors$", filename, re.I)
    ):
        raise ValueError("Choose one complete diffusion SafeTensors file with a publisher SHA256")
    file = matches[0]
    if (profile.pop("source_filename"), profile.pop("source_sha256")) != (filename, file["sha256"]):
        raise ValueError("The reviewed checkpoint header belongs to another immutable file")
    return HubVideoCandidate(
        id="hub-video-" + file["sha256"][:24],
        name=observation["repository"].rsplit("/", 1)[-1][:180],
        filename=filename,
        file=FileSpec(sha256=file["sha256"], size_bytes=file["size_bytes"], urls=(file["source_url"],)),
        **{k: observation[k] for k in ("repository", "revision", "source_url", "license", "license_url")},
        **profile,
    )


def recommendation(entry, hardware):
    ram = (hardware.get("memory") or {}).get("total_mib")

    def valid(v):
        return type(v) in {int, float} and math.isfinite(v) and v > 0

    devices = sorted(
        [
            v
            for v in hardware.get("gpus", [])
            if isinstance(v, dict)
            and type(v.get("index")) is int
            and v["index"] >= 0
            and valid(v.get("memory_total_mib"))
            and v["memory_total_mib"] >= 12288
        ],
        key=lambda v: v["index"],
    )
    fits = bool(entry.host_profile_compatible and valid(ram) and ram >= 24576 and devices)
    return {
        "fits": fits,
        "gpus": [devices[0]["index"]] if fits else [],
        "context_size": None,
        "reason": "Fixed 1280×704 Wan profile with explicit CPU offload, one 12-GiB GPU and 24-GiB physical RAM"
        if fits
        else "This video profile needs its compatible native engine, one 12-GiB GPU and 24-GiB physical RAM",
        "ram_mib": 11264,
        "minimum_physical_ram_mib": 24576,
        "minimum_vram_mib": 12288,
        "width": 1280,
        "height": 704,
        "maximum_frames": 81,
        "minimum_steps": 20,
        "cpu_offload": True,
    }


def refresh_plan(entry, check):
    check()
    report = VideoSetupClient(timeout=20).runtime_setup_catalog()
    check()
    if report.get("manifest_sha256") != entry.setup_manifest_sha256 or entry.slot not in report.get(
        "checkpoint_slots", []
    ):
        raise ValueError("The supported video recipe changed; inspect its source again")
    return HubVideoCandidate.model_validate({**entry.model_dump(mode="json"), **readiness(report)})
