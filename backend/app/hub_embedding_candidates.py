"""Pinned E5 ONNX source plus fixed tokenizer for the existing CPU memory service."""

import importlib.util
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.embedding_graph import MAX_MODEL_BYTES, PROFILE, fingerprint, recipe
from app.hub_sources import metadata_json, parse_source
from app.model_download_files import FileSpec
from app.model_source_recovery import source_identity


def available():
    return all(
        importlib.util.find_spec(name) is not None for name in ("onnx", "onnxruntime", "tokenizers", "numpy")
    )


class HubEmbeddingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: Literal["hub_embedding"] = "hub_embedding"
    id: str
    name: str = Field(min_length=1, max_length=180)
    capability: Literal["embedding"] = "embedding"
    runtime: Literal["onnx-cpu"] = "onnx-cpu"
    runtime_profile: None = None
    architecture: Literal["bert_e5_small"] = "bert_e5_small"
    quantization: Literal["F32"] = "F32"
    filename: str = Field(min_length=1, max_length=400)
    file: FileSpec
    tokenizer: FileSpec
    repository: str
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_url: str
    license: str = Field(min_length=1, max_length=120)
    license_url: str
    configuration: dict
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_url: str
    profile: Literal["e5-small-onnx-f32-v1"] = PROFILE
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    component_licenses: list[dict]

    @model_validator(mode="after")
    def complete(self):
        frozen = recipe(self.profile)
        tok = frozen["tokenizer"]
        if (
            self.id != "hub-embedding-" + self.file.sha256[:24]
            or len(self.file.urls) != 1
            or source_identity(self.file.urls[0]) != (self.repository, self.revision, self.filename)
            or parse_source(self.repository).repository != self.repository
            or self.source_url != f"https://huggingface.co/{self.repository}/tree/{self.revision}"
            or self.license_url != f"https://huggingface.co/{self.repository}/blob/{self.revision}/README.md"
            or self.config_url
            != f"https://huggingface.co/{self.repository}/resolve/{self.revision}/config.json"
            or fingerprint(self.configuration) != self.configuration_sha256
            or self.profile_sha256 != fingerprint(frozen)
            or any(self.configuration.get(k) != v for k, v in frozen["configuration"].items())
            or self.configuration.get("auto_map")
            or not self.filename.lower().endswith(".onnx")
            or not frozen["reference"]["size_bytes"] - 1024**2 <= self.file.size_bytes <= MAX_MODEL_BYTES
            or self.tokenizer
            != FileSpec(sha256=tok["sha256"], size_bytes=tok["size_bytes"], urls=(tok["url"],))
        ):
            raise ValueError("Choose a complete compatible F32 E5 export with its fixed tokenizer")
        return self


async def resolve_profile(observation, check):
    url = f"https://huggingface.co/{observation['repository']}/resolve/{observation['revision']}/config.json"
    configuration = await metadata_json(url, check)
    if (
        not isinstance(configuration, dict)
        or configuration.get("auto_map")
        or any(configuration.get(k) != v for k, v in recipe()["configuration"].items())
    ):
        raise ValueError("This encoder configuration needs its own compatible memory profile")
    return {
        "configuration": configuration,
        "configuration_sha256": fingerprint(configuration),
        "config_url": url,
        "profile": PROFILE,
        "profile_sha256": fingerprint(recipe()),
    }


def candidate_from_profile(observation, filename):
    matches = [
        v
        for v in observation["files"]
        if v["filename"] == filename and v.get("identity_available") and v.get("format") == "onnx"
    ]
    if len(matches) != 1:
        raise ValueError("Choose one complete ONNX encoder with a publisher SHA256")
    file, profile = matches[0], observation["embedding_profile"]
    tok = recipe()["tokenizer"]
    return HubEmbeddingCandidate(
        id="hub-embedding-" + file["sha256"][:24],
        name=observation["repository"].rsplit("/", 1)[-1][:180],
        filename=filename,
        file=FileSpec(sha256=file["sha256"], size_bytes=file["size_bytes"], urls=(file["source_url"],)),
        tokenizer=FileSpec(sha256=tok["sha256"], size_bytes=tok["size_bytes"], urls=(tok["url"],)),
        **{k: observation[k] for k in ("repository", "revision", "source_url", "license", "license_url")},
        **profile,
        component_licenses=[{"name": "Fixed E5 tokenizer · MIT", "url": recipe()["license_url"]}],
    )


def recommendation(entry, hardware):
    ram = (hardware.get("memory") or {}).get("total_mib")
    fits = available() and type(ram) in {int, float} and math.isfinite(ram) and ram >= 4096
    return {
        "fits": fits,
        "gpus": [],
        "context_size": None,
        "execution_device": "cpu",
        "ram_mib": 2048,
        "cpu_threads": 2,
        "dimension": 384,
        "maximum_tokens_per_chunk": 512,
        "reason": "Local CPU encoder · 384 dimensions · two threads and a 2-GiB process limit"
        if fits
        else "This encoder needs the installed ONNX CPU engine and at least 4 GiB physical RAM",
    }


def assessment(entry, hardware, storage):
    plan = recommendation(entry, hardware)
    free, head = (storage or {}).get("free_bytes"), (storage or {}).get("headroom_bytes")
    needed = entry.file.size_bytes + entry.tokenizer.size_bytes + 128 * 1024**2
    known = all(type(v) in {int, float} and math.isfinite(v) and v >= 0 for v in (free, head))
    ram = (hardware.get("memory") or {}).get("total_mib")
    fit = (
        "estimated_fit"
        if plan["fits"]
        else "not_recommended"
        if type(ram) in {int, float} and math.isfinite(ram) and ram > 0
        else "unknown"
    )
    return {
        "disk": {
            "status": "unknown" if not known else "file_fits" if free >= needed + head else "insufficient",
            "file_bytes": entry.file.size_bytes,
            "free_bytes": free,
            "headroom_bytes": head,
            "complete_install_budget_known": True,
            "install_bytes_upper_bound": needed,
            "note": "Complete encoder/tokenizer files with bounded working reserve.",
        },
        "runtime_status": "supported_architecture_plan" if available() else "runtime_unavailable",
        "hardware_status": fit,
        "profiles": [
            {
                "catalog_id": entry.id,
                "name": entry.name,
                "quantization": "F32",
                "capability": "embedding",
                "runtime": entry.runtime,
                "fit": fit,
                "occupancy": "not_applicable",
                "recommendation": plan,
                "locally_qualified": False,
                "provenance": "pinned_encoder_configuration_and_fixed_tokenizer",
            }
        ],
        "reason": "Potentially compatible F32 E5 export; its complete graph and precision are verified after download. Runs on CPU, without GPU or cloud fallback.",
        "automatic_ram_offload": False,
        "automatic_cloud_fallback": False,
    }
