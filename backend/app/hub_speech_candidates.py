"""Pinned Chatterbox checkpoints compose with the existing offline speech preparation."""

import math
from typing import Literal

from app.hub_checkpoint_headers import inspect as inspect_header
from app.hub_native_candidates import HubNativeCandidate
from app.model_download_files import FileSpec
from app.speech_setup_client import SpeechSetupClient

PROFILE = "chatterbox-v3-linux-x86-64-python312-v1"
SLOT = "chatterbox-v3-t3-v1"


class HubSpeechCandidate(HubNativeCandidate):
    PREFIX = "hub-speech-"
    PROFILE = PROFILE
    SLOT = SLOT
    ROLE = "chatterbox_t3"
    MODEL_FIELD = "filename"
    MODELS = frozenset(
        {
            "ve.pt",
            "t3_mtl23ls_v3.safetensors",
            "s3gen.pt",
            "grapheme_mtl_merged_expanded_v1.json",
            "conds.pt",
            "Cangjie5_TC.json",
        }
    )

    origin: Literal["hub_speech"] = "hub_speech"
    capability: Literal["speech"] = "speech"
    runtime: Literal["chatterbox"] = "chatterbox"
    architecture: Literal["chatterbox_v3"] = "chatterbox_v3"
    quantization: Literal["F32"] = "F32"


def readiness(report):
    ready = (report.get("managed_speech") or {}).get("available") is True
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
    report = SpeechSetupClient(timeout=20).runtime_setup_catalog()
    check()
    slots = [v for v in report.get("checkpoint_slots", []) if v.get("profile") == SLOT]
    if len(slots) != 1:
        raise ValueError("Update the Host Runner to inspect compatible speech checkpoint slots")
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
    profile = dict(observation["speech_profile"])
    if (profile.pop("source_repository"), profile.pop("source_revision")) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The speech profile belongs to another immutable source")
    matches = [v for v in observation["files"] if v["filename"] == filename]
    if (
        len(matches) != 1
        or not matches[0].get("identity_available")
        or matches[0].get("format") != "safetensors"
    ):
        raise ValueError("Choose one complete T3 SafeTensors file with a publisher SHA256")
    file = matches[0]
    if (profile.pop("source_filename"), profile.pop("source_sha256")) != (filename, file["sha256"]):
        raise ValueError("The reviewed checkpoint header belongs to another immutable file")
    return HubSpeechCandidate(
        id="hub-speech-" + file["sha256"][:24],
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
            and device["memory_total_mib"] >= 6144
        ],
        key=lambda device: device["index"],
    )
    fits = bool(entry.host_profile_compatible and valid(ram) and ram >= 16384 and devices)
    return {
        "fits": fits,
        "gpus": [devices[0]["index"]] if fits else [],
        "context_size": None,
        "reason": "Fixed local Polish Chatterbox v3 profile, one 6-GiB GPU and 16-GiB physical RAM"
        if fits
        else "This speech profile needs its compatible native engine, one 6-GiB GPU and 16-GiB physical RAM",
        "ram_mib": 11264,
        "minimum_physical_ram_mib": 16384,
        "minimum_vram_mib": 6144,
        "maximum_text_characters": 1000,
        "cpu_offload": False,
    }


def refresh_plan(entry, check):
    check()
    report = SpeechSetupClient(timeout=20).runtime_setup_catalog()
    check()
    if report.get("manifest_sha256") != entry.setup_manifest_sha256 or entry.slot not in report.get(
        "checkpoint_slots", []
    ):
        raise ValueError("The supported speech recipe changed; inspect its source again")
    return HubSpeechCandidate.model_validate({**entry.model_dump(mode="json"), **readiness(report)})
