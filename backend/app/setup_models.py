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


CANDIDATES = (
    _candidate("Q4_K_M", 2497281312, "b1324e2f1bd2e0610d591f54f93e38d90b187f69d1f215f4cace349eade678d7"),
    _candidate("Q8_0", 4280405792, "f3b6a790d226efadd863152415713d4d177a22e80eb37bc54537dab110062f31"),
)


def candidate(identity):
    return next((entry for entry in CANDIDATES if entry.id == identity), None)
