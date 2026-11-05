"""Pinned ACE-Step checkpoints compose with the existing offline music preparation."""

import math
from typing import Literal

from app.hub_checkpoint_headers import inspect as inspect_header
from app.hub_native_candidates import HubNativeCandidate
from app.model_download_files import FileSpec
from app.music_setup_client import MusicSetupClient

PROFILE = "ace-step15-turbo-linux-x86-64-python312-v1"
SLOT = "ace-step15-turbo-diffusion-v1"


class HubMusicCandidate(HubNativeCandidate):
    PREFIX = "hub-music-"
    PROFILE = PROFILE
    SLOT = SLOT
    ROLE = "ace_step15_turbo_diffusion"
    MODEL_FIELD = "filename"
    MODELS = frozenset(
        [
            "Qwen3-Embedding-0.6B/added_tokens.json",
            "Qwen3-Embedding-0.6B/chat_template.jinja",
            "Qwen3-Embedding-0.6B/config.json",
            "Qwen3-Embedding-0.6B/merges.txt",
            "Qwen3-Embedding-0.6B/model.safetensors",
            "Qwen3-Embedding-0.6B/special_tokens_map.json",
            "Qwen3-Embedding-0.6B/tokenizer.json",
            "Qwen3-Embedding-0.6B/tokenizer_config.json",
            "Qwen3-Embedding-0.6B/vocab.json",
            "acestep-v15-turbo/config.json",
            "acestep-v15-turbo/configuration_acestep_v15.py",
            "acestep-v15-turbo/model.safetensors",
            "acestep-v15-turbo/modeling_acestep_v15_turbo.py",
            "acestep-v15-turbo/silence_latent.pt",
            "vae/config.json",
            "vae/diffusion_pytorch_model.safetensors",
        ]
    )

    origin: Literal["hub_music"] = "hub_music"
    capability: Literal["music"] = "music"
    runtime: Literal["ace-step-1.5"] = "ace-step-1.5"
    architecture: Literal["ace_step15_turbo"] = "ace_step15_turbo"
    quantization: Literal["BF16"] = "BF16"


def readiness(report):
    ready = (report.get("managed_music") or {}).get("available") is True
    required = (report.get("storage") or {}).get("required_bytes")
    if type(required) is not int or required < 0:
        required = sum(v["size_bytes"] for v in report["recipe"]["inputs"]) + 8 * 1024**3
    return {
        "prepare_engine": not ready,
        "preparation_available": ready or report.get("installation_available") is True,
        "host_profile_compatible": (report.get("recommendation") or {}).get("fits") is True,
        "preparation_notice": (report.get("installation_notice") or "")[:500],
        "prerequisite_budget_bytes": 0 if ready else required,
    }


async def resolve_profile(observation, check, filename=None, *, _header=None):
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
    report = MusicSetupClient(timeout=20).runtime_setup_catalog()
    check()
    slots = [v for v in report.get("checkpoint_slots", []) if v.get("profile") == SLOT]
    if len(slots) != 1:
        raise ValueError("Update the Host Runner to inspect compatible music checkpoint slots")
    slot = slots[0]
    header = await inspect_header(file, check) if _header is None else _header
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
    profile = dict(observation["music_profile"])
    if (profile.pop("source_repository"), profile.pop("source_revision")) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The music profile belongs to another immutable source")
    matches = [v for v in observation["files"] if v["filename"] == filename]
    if (
        len(matches) != 1
        or not matches[0].get("identity_available")
        or matches[0].get("format") != "safetensors"
    ):
        raise ValueError("Choose one complete diffusion SafeTensors file with a publisher SHA256")
    file = matches[0]
    if (profile.pop("source_filename"), profile.pop("source_sha256")) != (filename, file["sha256"]):
        raise ValueError("The reviewed checkpoint header belongs to another immutable file")
    return HubMusicCandidate(
        id="hub-music-" + file["sha256"][:24],
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
        "reason": "Fixed local ACE-Step 1.5 Turbo profile, one 12-GiB GPU and 24-GiB physical RAM"
        if fits
        else "This music profile needs its compatible native engine, one 12-GiB GPU and 24-GiB physical RAM",
        "ram_mib": 18432,
        "minimum_physical_ram_mib": 24576,
        "minimum_vram_mib": 12288,
        "maximum_seconds": 600,
        "cpu_offload": True,
    }


def refresh_plan(entry, check):
    check()
    report = MusicSetupClient(timeout=20).runtime_setup_catalog()
    check()
    if report.get("manifest_sha256") != entry.setup_manifest_sha256 or entry.slot not in report.get(
        "checkpoint_slots", []
    ):
        raise ValueError("The supported music recipe changed; inspect its source again")
    return HubMusicCandidate.model_validate({**entry.model_dump(mode="json"), **readiness(report)})
