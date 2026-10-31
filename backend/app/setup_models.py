"""Reviewed download candidates, not an assertion of installed runtime readiness.

Source/LFS identities were checked through the publishers' Hugging Face APIs on
2026-10-30. Importing the catalog never accesses the network or downloads weights.
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
    quantization: Literal["Q4_K_M", "Q8_0"]
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
    architecture: Literal["qwen3"] = "qwen3"
    attention_layers: int = 36
    kv_heads: int = 8
    key_length: int = 128
    value_length: int = 128


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
)


def candidate(identity):
    return next((entry for entry in CANDIDATES if entry.id == identity), None)


STARTER_CANDIDATE_IDS = frozenset(entry.id for entry in CANDIDATES[:2])
