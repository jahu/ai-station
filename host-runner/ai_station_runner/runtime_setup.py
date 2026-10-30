"""Pinned runtime planning/inspection. Installation remains unpublished.

A Docker image's presence is not a working GPU/runtime qualification. This module
never pulls, tags, starts, stops or removes anything. Recipes are host-owned, not
caller-selected registry references or commands.
"""

import hashlib
import json
import platform
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from ai_station_runner import llama_runtime

REFERENCE = (
    "ghcr.io/ggml-org/llama.cpp@sha256:95cdc1510dbc5bc15735529353d72ace9fc96b9aeb0dd6c4cdaf1a6b3f70776f"
)


class RuntimeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["llamacpp-cuda-linux-amd64-v1"]


def recipe(selection: RuntimeSelection) -> dict:
    # An immutable manifest qualified with the app-owned Q4 model, 32k Q8 KV
    # context and two private consumers on Linux/NVIDIA. No moving Docker tag.
    return {
        "profile": selection.profile,
        "name": "llama.cpp · Linux NVIDIA",
        "image_reference": REFERENCE,
        "platform": "linux/amd64",
        "capability": "chat",
        "source_url": "https://github.com/ggml-org/llama.cpp",
        "qualification": "Linux NVIDIA; Q4 GGUF; 32768-token Q8 KV context",
    }


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspect_image(selection: RuntimeSelection) -> dict:
    frozen = recipe(selection)
    supported = platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}
    result = {
        "recipe": frozen,
        "manifest_sha256": fingerprint(frozen),
        "platform_supported": supported,
        "image": {"status": "unknown", "present": False, "id": None},
        "installation_available": False,
        "installation_notice": "Runtime download cancellation and recovery qualification is still required",
        "inference_tested_now": False,
    }
    if not supported:
        result["image"]["notice"] = "This CUDA image profile requires a Linux x86-64 Runner"
        return result
    try:
        raw = llama_runtime.docker("image", "inspect", REFERENCE, "--format", "{{json .}}", missing_ok=True)
        if raw is None:
            result["image"]["status"] = "unavailable"
            return result
        observed = json.loads(raw)
        if (
            not isinstance(observed, dict)
            or observed.get("Os") != "linux"
            or observed.get("Architecture") != "amd64"
            or not isinstance(observed.get("Id"), str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", observed["Id"])
            or not isinstance(observed.get("RepoDigests"), list)
            or REFERENCE not in observed["RepoDigests"]
        ):
            raise ValueError("The local image does not match its pinned recipe")
        result["image"] = {"status": "available", "present": True, "id": observed["Id"]}
    except (HTTPException, OSError, ValueError, TypeError):
        result["image"]["notice"] = "The pinned runtime image inspection could not be confirmed"
    return result
