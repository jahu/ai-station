"""Pinned runtime planning/inspection for the typed native preparation service.

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
    profile: Literal[
        "llamacpp-cuda-linux-amd64-v1", "qwen-image21-cuda-linux-amd64-v1", "llamacpp-cpu-linux-amd64-v1"
    ]


def recipe(selection: RuntimeSelection) -> dict:
    from ai_station_runner import cpu_runtime_profile as cpu

    if selection.profile == cpu.PROFILE:
        return cpu.recipe()
    if selection.profile == "qwen-image21-cuda-linux-amd64-v1":
        from ai_station_runner.image_setup import recipe as image_recipe

        return image_recipe()
    # An immutable manifest qualified with the app-owned Q4 model, 32k Q8 KV
    # context and two private consumers on Linux/NVIDIA. No moving Docker tag.
    return {
        "profile": selection.profile,
        "name": "llama.cpp · Linux NVIDIA",
        "image_reference": REFERENCE,
        "platform": "linux/amd64",
        "license": "MIT (llama.cpp); bundled CUDA and base-system licenses",
        "license_url": "https://github.com/ggml-org/llama.cpp/blob/master/LICENSE",
        "cuda_license_url": "https://docs.nvidia.com/cuda/eula/index.html",
        "download_bytes": 2589389163,
        "minimum_free_bytes": 12 * 1024**3,
        "layers": {
            "5a7813e071bfadf18aaa6ca8318be4824a9b6297b3240f2cc84c1db6f4113040": 29754290,
            "a102f36d092c0e9e0bef8c97854f606af9156aa36ab408e6fa4b88e27124a7e6": 6947129,
            "05ec76e31584ec109785cc7045bd88df0240411233c2fcdad66b621c662034c0": 64290636,
            "398182656c471d6ecca3c2d6d30e97193b40ffc8028a94515093960322f3d64e": 183,
            "73389fbd088f5ed5d9fd258baced59de092978b4f483920ea6d074522a105119": 6885,
            "cbb9175a9bc5f6553f8c0c5025ea9521898b8a3956ee24798dc35c24c6185053": 2058008382,
            "3d6ab8c799cda2f4c6a6277b0e24dd2231c5de83b0316968b7cce81156bb8be0": 59618,
            "7209097bfb98d6f8b422984480f1fddead5ea62f8900ff6b6548e060b71aca76": 1684,
            "545a3ada5b6bc612a11c13a659775d67eeda5a61615e7f49c76ecd24adcad626": 1524,
            "b51badbbc1b1fe7f4fdd50cb8a98878132db17b3a86eeb9960e58c4f7c3a608f": 261903208,
            "0ab2b808eb08a8e02b09898ff8af07c1392463f941c7ead3ee385873d38b04ac": 168372265,
            "41b64f0430e8fdaf37673b3bae57567ef4c858b6ac2d3f938daffe2f84aad93f": 25227,
            "4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1": 32,
        },
        "capability": "chat",
        "source_url": "https://github.com/ggml-org/llama.cpp",
        "qualification": "Linux NVIDIA; Q4 GGUF; 32768-token Q8 KV context",
    }


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def platform_supported():
    return platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}


def validate_image(observed, reference):
    if (
        not isinstance(observed, dict)
        or observed.get("Os") != "linux"
        or observed.get("Architecture") != "amd64"
        or not isinstance(observed.get("Id"), str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", observed["Id"])
        or not isinstance(observed.get("RepoDigests"), list)
        or reference not in observed["RepoDigests"]
    ):
        raise ValueError("The local image does not match its pinned recipe")
    return {"id": observed["Id"], "reference": reference, "platform": "linux/amd64"}


def inspect_image(selection: RuntimeSelection) -> dict:
    frozen = recipe(selection)
    supported = platform_supported()
    result = {
        "recipe": frozen,
        "manifest_sha256": fingerprint(frozen),
        "platform_supported": supported,
        "image": {"status": "unknown", "present": False, "id": None},
        "installation_available": False,
        "installation_notice": "The runtime preparation worker and account cleanup are still being qualified",
        "inference_tested_now": False,
    }
    if not supported:
        result["image"]["notice"] = (
            "This CPU image profile requires a Linux x86-64 Runner"
            if selection.profile == "llamacpp-cpu-linux-amd64-v1"
            else "This CUDA image profile requires a Linux x86-64 Runner"
        )
        return result
    try:
        raw = llama_runtime.docker(
            "image", "inspect", frozen["image_reference"], "--format", "{{json .}}", missing_ok=True
        )
        if raw is None:
            result["image"]["status"] = "unavailable"
            return result
        observed = json.loads(raw)
        validate_image(observed, frozen["image_reference"])
        result["image"] = {"status": "available", "present": True, "id": observed["Id"]}
    except (HTTPException, OSError, ValueError, TypeError):
        result["image"]["notice"] = "The pinned runtime image inspection could not be confirmed"
    return result


def image_observation(*, app_owned=False, runtime_profile=None):
    """Resolve one installed image observation without replacing configured tags."""
    from ai_station_runner.config import get_settings

    if runtime_profile is not None:
        from ai_station_runner import cpu_runtime_profile as cpu

        if runtime_profile != cpu.PROFILE or not cpu.QUALIFIED or not app_owned:
            raise ValueError("The managed CPU profile is unavailable or not explicitly owned")
        report = inspect_image(RuntimeSelection(profile=cpu.PROFILE))
        return cpu.REFERENCE, report["image"].get("id")
    configured = get_settings().llama_image
    existing = llama_runtime.docker("image", "inspect", configured, "--format", "{{.Id}}", missing_ok=True)
    if existing is not None or not app_owned and configured != "ghcr.io/ggml-org/llama.cpp:server-cuda":
        return configured, existing
    report = inspect_image(RuntimeSelection(profile="llamacpp-cuda-linux-amd64-v1"))
    if report["image"]["present"]:
        return REFERENCE, report["image"].get("id")
    return configured, None


def image_reference(*, app_owned=False):
    from ai_station_runner.config import get_settings

    configured = get_settings().llama_image
    if not app_owned and configured != "ghcr.io/ggml-org/llama.cpp:server-cuda":
        return configured
    return image_observation(app_owned=app_owned)[0]
