"""Pinned Sonic tensor weights compose with the existing offline avatar preparation."""

import math
from typing import Literal

from pydantic import model_validator

from app.avatar_setup_client import AvatarSetupClient
from app.hub_native_candidates import HubNativeCandidate
from app.hub_tensor_headers import inspect as inspect_header
from app.model_download_files import FileSpec

PROFILE = "sonic-whole-linux-x86-64-python310-v1"
SLOT = "sonic-whole-unet-v1"


class HubAvatarCandidate(HubNativeCandidate):
    PREFIX = "hub-avatar-"
    PROFILE = PROFILE
    SLOT = SLOT
    ROLE = "sonic_adapted_unet"
    MODEL_FIELD = "filename"
    MODELS = frozenset(
        [
            "RIFE/flownet.pkl",
            "Sonic/audio2bucket.pth",
            "Sonic/audio2token.pth",
            "Sonic/unet.pth",
            "yoloface_v5m.pt",
            "stable-video-diffusion-img2vid-xt/image_encoder/config.json",
            "stable-video-diffusion-img2vid-xt/image_encoder/model.fp16.safetensors",
            "stable-video-diffusion-img2vid-xt/scheduler/scheduler_config.json",
            "stable-video-diffusion-img2vid-xt/unet/config.json",
            "stable-video-diffusion-img2vid-xt/vae/config.json",
            "stable-video-diffusion-img2vid-xt/vae/diffusion_pytorch_model.fp16.safetensors",
            "whisper-tiny/config.json",
            "whisper-tiny/model.safetensors",
            "whisper-tiny/preprocessor_config.json",
        ]
    )

    origin: Literal["hub_avatar"] = "hub_avatar"
    capability: Literal["avatar"] = "avatar"
    configuration_filename: Literal["pytorch-zip-tensor-metadata"] = "pytorch-zip-tensor-metadata"
    runtime: Literal["sonic"] = "sonic"
    architecture: Literal["sonic_whole_unet"] = "sonic_whole_unet"
    quantization: Literal["F32"] = "F32"

    @model_validator(mode="after")
    def tensor_data_only(self):
        if (
            self.checkpoint_header.get("source") != "pytorch_zip_tensor_data"
            or self.checkpoint_header.get("module_metadata_sha256") != self.slot.get("module_metadata_sha256")
            or self.checkpoint_header.get("storage_layout_verified") is not False
            or self.checkpoint_header.get("dtypes") != ["F32"]
        ):
            raise ValueError(
                "Avatar weights require the closed tensor-data graph and module-version observation"
            )
        return self


def readiness(report):
    ready = (report.get("managed_avatar") or {}).get("prepared") is True
    qualified = report.get("checkpoint_inference_available") is True
    required = (report.get("storage") or {}).get("required_bytes")
    if type(required) is not int or required < 0:
        required = sum(v["size_bytes"] for v in report["recipe"]["inputs"]) + 12 * 1024**3
    return {
        "prepare_engine": not ready,
        "preparation_available": qualified and (ready or report.get("installation_available") is True),
        "host_profile_compatible": (report.get("recommendation") or {}).get("fits") is True,
        "preparation_notice": (
            (report.get("installation_notice") or "")
            if qualified
            else "Selected avatar checkpoint inference is still being qualified"
        )[:500],
        "prerequisite_budget_bytes": 0 if ready else required,
    }


async def resolve_profile(observation, check, filename=None, *, _header=None):
    matches = [
        f
        for f in observation["files"]
        if f.get("format") in {"pth", "pt", "bin"}
        and f.get("identity_available")
        and (filename is None or f["filename"] == filename)
    ]
    if len(matches) != 1:
        raise ValueError("Choose a specific complete checkpoint file to inspect its actual graph")
    file = matches[0]
    check()
    report = AvatarSetupClient(timeout=20).runtime_setup_catalog()
    check()
    slots = [v for v in report.get("checkpoint_slots", []) if v.get("profile") == SLOT]
    if len(slots) != 1:
        raise ValueError("Update the Host Runner to inspect compatible avatar checkpoint slots")
    slot = slots[0]
    header = await inspect_header(file, check) if _header is None else _header
    if (
        header["tensor_count"] != slot["tensor_count"]
        or header["schema_sha256"] != slot["schema_sha256"]
        or header["dtypes"] != slot["allowed_dtypes"]
        or header.get("source") != "pytorch_zip_tensor_data"
        or header.get("module_metadata_sha256") != slot["module_metadata_sha256"]
        or header.get("storage_layout_verified") is not False
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
        "configuration_filename": "pytorch-zip-tensor-metadata",
        "config_url": file["source_url"],
        "checkpoint_header": header,
        "slot": slot,
        "component_licenses": report.get("licenses", []),
        "setup_recipe": report["recipe"],
        "setup_manifest_sha256": report["manifest_sha256"],
        **readiness(report),
    }


def candidate_from_profile(observation, filename):
    profile = dict(observation["avatar_profile"])
    if (profile.pop("source_repository"), profile.pop("source_revision")) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The avatar profile belongs to another immutable source")
    matches = [v for v in observation["files"] if v["filename"] == filename]
    if (
        len(matches) != 1
        or not matches[0].get("identity_available")
        or matches[0].get("format") not in {"pth", "pt", "bin"}
    ):
        raise ValueError("Choose one complete Sonic tensor ZIP file with a publisher SHA256")
    file = matches[0]
    if (profile.pop("source_filename"), profile.pop("source_sha256")) != (filename, file["sha256"]):
        raise ValueError("The reviewed checkpoint header belongs to another immutable file")
    return HubAvatarCandidate(
        id="hub-avatar-" + file["sha256"][:24],
        name=observation["repository"].rsplit("/", 1)[-1][:180],
        filename=filename,
        file=FileSpec(sha256=file["sha256"], size_bytes=file["size_bytes"], urls=(file["source_url"],)),
        **{k: observation[k] for k in ("repository", "revision", "source_url", "license", "license_url")},
        **profile,
    )


def recommendation(entry, hardware):
    ram = (hardware.get("memory") or {}).get("total_mib")

    def valid(value):
        return type(value) in {int, float} and math.isfinite(value) and value > 0

    devices = sorted(
        [
            device
            for device in hardware.get("gpus", [])
            if isinstance(device, dict)
            and type(device.get("index")) is int
            and device["index"] >= 0
            and valid(device.get("memory_total_mib"))
            and device["memory_total_mib"] >= 12288
        ],
        key=lambda device: device["index"],
    )
    fits = bool(entry.host_profile_compatible and valid(ram) and ram >= 24576 and devices)
    return {
        "fits": fits,
        "gpus": [devices[0]["index"]] if fits else [],
        "context_size": None,
        "reason": "Fixed local Sonic whole-recording profile, one 12-GiB GPU and 24-GiB physical RAM"
        if fits
        else "This avatar profile needs its compatible native engine, one 12-GiB GPU and 24-GiB physical RAM",
        "ram_mib": 18432,
        "minimum_physical_ram_mib": 24576,
        "minimum_vram_mib": 12288,
        "maximum_seconds": 60,
        "cpu_offload": True,
    }


class AvatarReadinessPending(Exception):
    """A complete engine is still being hashed; never register or redownload it."""


def require_ready(report):
    managed = report.get("managed_avatar") or {}
    if managed.get("prepared") is True and managed.get("readiness") == "checking":
        raise AvatarReadinessPending()
    if managed.get("available") is not True:
        raise ValueError("The reviewed avatar engine and companions are not ready; inspect preparation")


def refresh_plan(entry, check, *, require_engine=False):
    check()
    report = AvatarSetupClient(timeout=20).runtime_setup_catalog()
    check()
    if report.get("manifest_sha256") != entry.setup_manifest_sha256 or entry.slot not in report.get(
        "checkpoint_slots", []
    ):
        raise ValueError("The supported avatar recipe changed; inspect its source again")
    if require_engine:
        require_ready(report)
    return HubAvatarCandidate.model_validate({**entry.model_dump(mode="json"), **readiness(report)})
