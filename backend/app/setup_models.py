"""Reviewed download candidates, not an assertion of installed runtime readiness.

Source/LFS identities were checked through the publishers' Hugging Face APIs on
2026-10-30–31. Importing the catalog never accesses the network or downloads weights.
Actual GGUF inspection and the existing load admission remain authoritative.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.model_download_files import FileSpec

REPOSITORY = "mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF"
REVISION = "c9e90669eeb205d5af35c28a3e9983fc9293c2ec"
ORIGINAL = "huihui-ai/Huihui-Qwen3-4B-Instruct-2507-abliterated"
ORIGINAL_REVISION = "c9bd464550d4078c72af0dd22aa18d0437868ce3"


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    name: str
    capability: Literal["chat"] = "chat"
    runtime: Literal["llama.cpp"] = "llama.cpp"
    format: Literal["gguf"] = "gguf"
    quantization: Literal["Q4_K_M", "Q8_0", "IQ2_XS"]
    filename: str
    file: FileSpec
    repository: str = REPOSITORY
    revision: str = REVISION
    license: Literal["Apache-2.0"] = "Apache-2.0"
    source_url: str = f"https://huggingface.co/{REPOSITORY}/tree/{REVISION}"
    license_url: str = f"https://huggingface.co/{ORIGINAL}/blob/{ORIGINAL_REVISION}/README.md"
    config_url: str = f"https://huggingface.co/{ORIGINAL}/resolve/{ORIGINAL_REVISION}/config.json"
    trained_context: int = 262144
    # Declared architecture hints are not a verified/native GGUF observation.
    architecture: Literal["qwen3", "qwen35"] = "qwen3"
    attention_layers: int = 36
    kv_heads: int = 8
    key_length: int = 128
    value_length: int = 128
    # Omit legacy defaults so existing durable download identities do not change.
    state_reserve_mib: int = Field(default=0, ge=0, le=4096, exclude_if=lambda v: v == 0)
    context_ceiling: int = Field(default=32768, ge=4096, le=131072, exclude_if=lambda v: v == 32768)
    runtime_profile: (
        Literal[
            "llamacpp-cpu-linux-amd64-v1",
            "llamacpp-native-darwin-arm64-b12032-v2",
            "llamacpp-native-darwin-x86_64-b12032-v2",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda v: v is None)
    description: str = Field(default="", max_length=240, exclude_if=lambda v: not v)


def _candidate(quantization, size, sha):
    filename = f"Huihui-Qwen3-4B-Instruct-2507-abliterated.{quantization}.gguf"
    return Candidate(
        id="huihui-qwen3-4b-2507-" + quantization.lower().replace("_", ""),
        name="Huihui Qwen3 · 4B",
        quantization=quantization,
        filename=filename,
        file=FileSpec(
            sha256=sha,
            size_bytes=size,
            urls=(f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{filename}",),
        ),
    )


def _larger_candidate(parameters, quantization, size, sha):
    count, repository, revision, source_revision, layers = parameters
    original = f"mlabonne/Qwen3-{count}B-abliterated"
    filename = f"Qwen3-{count}B-abliterated.{quantization}.gguf"
    return Candidate(
        id=f"mlabonne-qwen3-{count}b-" + quantization.lower().replace("_", ""),
        name=f"Qwen3 · {count}B · mlabonne",
        quantization=quantization,
        filename=filename,
        file=FileSpec(
            sha256=sha,
            size_bytes=size,
            urls=(f"https://huggingface.co/{repository}/resolve/{revision}/{filename}",),
        ),
        repository=repository,
        revision=revision,
        source_url=f"https://huggingface.co/{repository}/tree/{revision}",
        license_url=f"https://huggingface.co/{original}/blob/{source_revision}/README.md",
        config_url=f"https://huggingface.co/{original}/resolve/{source_revision}/config.json",
        trained_context=40960,
        attention_layers=layers,
    )


def _rvn_candidate(quantization, size, sha, description):
    repository = "0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF"
    revision = "ab8d7bd81d03117501e4da60cccdff4c80f0eea0"
    original_revision = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
    filename = f"RVN-{quantization}-multilingual.gguf"
    return Candidate(
        id="rvn-qwen38-27b-" + quantization.lower().replace("_", ""),
        name="Qwen3.8 RVN · 27B",
        quantization=quantization,
        filename=filename,
        file=FileSpec(
            sha256=sha,
            size_bytes=size,
            urls=(f"https://huggingface.co/{repository}/resolve/{revision}/{filename}",),
        ),
        repository=repository,
        revision=revision,
        source_url=f"https://huggingface.co/{repository}/tree/{revision}",
        license_url=f"https://huggingface.co/{repository}/blob/{revision}/README.md",
        config_url=f"https://huggingface.co/Qwen/Qwen3.8-27B/resolve/{original_revision}/config.json",
        architecture="qwen35",
        attention_layers=16,
        kv_heads=4,
        key_length=256,
        value_length=256,
        state_reserve_mib=512,
        context_ceiling=131072,
        description=description,
    )


CANDIDATES = (
    _candidate("Q4_K_M", 2497281312, "b1324e2f1bd2e0610d591f54f93e38d90b187f69d1f215f4cace349eade678d7"),
    _candidate("Q8_0", 4280405792, "f3b6a790d226efadd863152415713d4d177a22e80eb37bc54537dab110062f31"),
    _larger_candidate(
        (
            8,
            "mradermacher/Qwen3-8B-abliterated-GGUF",
            "24198a3d288997af9fd7f09c54c84535396f7e77",
            "30c72fa348f37c72d12ecbb259068ddee98aa9ed",
            36,
        ),
        "Q4_K_M",
        5027783936,
        "13b309e6d941af001345c3f531ef401e2212e855f38ec81bdacb75d0bb5abecd",
    ),
    _larger_candidate(
        (
            8,
            "mradermacher/Qwen3-8B-abliterated-GGUF",
            "24198a3d288997af9fd7f09c54c84535396f7e77",
            "30c72fa348f37c72d12ecbb259068ddee98aa9ed",
            36,
        ),
        "Q8_0",
        8709518592,
        "6ec285379fbee1c880620c1959868cf120194d40105733a1774bb9293c6efa47",
    ),
    _larger_candidate(
        (
            14,
            "mradermacher/Qwen3-14B-abliterated-GGUF",
            "53729450c82efabb1b3a00ea4637df10240b1719",
            "9d8db58cddb750e732cd2179fa504e8830b733ce",
            40,
        ),
        "Q4_K_M",
        9001753408,
        "b36d0edb573c2562d8e45e839aa8e3f2c559640b42bf4eb5d2a562d2e3fa9401",
    ),
    _larger_candidate(
        (
            14,
            "mradermacher/Qwen3-14B-abliterated-GGUF",
            "53729450c82efabb1b3a00ea4637df10240b1719",
            "9d8db58cddb750e732cd2179fa504e8830b733ce",
            40,
        ),
        "Q8_0",
        15698534208,
        "1600956488a618f5722e53b9def34315ec724ff48cf1373f304c271117c051d4",
    ),
    _rvn_candidate(
        "Q4_K_M",
        16547400224,
        "9ed40ccc8b8432f38b9a85d0ca67928167f5719e8c10bd299e56d34facaf6e61",
        "Quality-focused 27B model with context sized for your GPUs.",
    ),
    _rvn_candidate(
        "IQ2_XS",
        9090591264,
        "9e7995899191c94875b3962443320452cd092608c06caae2b02e84a27bf2ae61",
        "Smaller download and more context headroom. Lower precision can reduce answer quality.",
    ),
)


CPU_PROFILE = "llamacpp-cpu-linux-amd64-v1"
CPU_CANDIDATE_ID = "huihui-qwen3-4b-2507-q4km-cpu"
CANDIDATES = (
    *CANDIDATES,
    CANDIDATES[0].model_copy(
        update={
            "id": CPU_CANDIDATE_ID,
            "name": "Huihui Qwen3 · 4B · CPU",
            "runtime_profile": CPU_PROFILE,
            "context_ceiling": 4096,
            "description": "Runs on your CPU without NVIDIA. Uses system RAM and is slower than GPU inference.",
        }
    ),
)


# Reuse the reviewed bytes and licenses, preserving every legacy manifest.
# Native CPU offers do not assert Metal or dedicated GPU-memory support.
CANDIDATES = (
    *CANDIDATES,
    *(
        Candidate.model_validate(
            {
                **entry.model_dump(),
                "id": entry.id + "-macos-" + architecture.replace("_", "-") + "-cpu",
                "name": entry.name + " · Mac CPU",
                "runtime_profile": "llamacpp-native-darwin-" + architecture + "-b12032-v2",
                "context_ceiling": 4096,
                "description": "Native llama.cpp on Mac. Uses system RAM; CPU inference is slower than GPU inference.",
            }
        )
        for architecture in ("arm64", "x86_64")
        for entry in CANDIDATES[:6]
    ),
)


def candidate(identity):
    return next((entry for entry in CANDIDATES if entry.id == identity), None)


STARTER_CANDIDATE_IDS = frozenset(entry.id for entry in CANDIDATES[:2])
