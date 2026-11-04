"""Pinned image checkpoints bind to an existing fixed engine and companion set."""

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.hub_sources import COMMIT, metadata_json, parse_source
from app.model_download_files import FileSpec
from app.model_setup import fingerprint
from app.model_source_recovery import source_identity

PROFILE = "qwen-image21-cuda-linux-amd64-v1"
SLOT = "qwen-image21-diffusion-v1"
GEOMETRY = {
    "_class_name": "QwenImage21Transformer2DModel",
    "attention_head_dim": 128,
    "axes_dims_rope": [16, 56, 56],
    "context_in_dim": 4096,
    "in_channels": 64,
    "num_attention_heads": 32,
    "num_layers": 32,
    "out_channels": 64,
    "patch_size": 1,
    "mlp_ratio": 3,
    "eps": 1e-6,
    "causal_condition": True,
}


class HubImageCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: Literal["hub_image"] = "hub_image"
    id: str
    name: str = Field(min_length=1, max_length=180)
    capability: Literal["image"] = "image"
    runtime: Literal["stable-diffusion.cpp"] = "stable-diffusion.cpp"
    runtime_profile: None = None
    architecture: Literal["qwen_image21"] = "qwen_image21"
    quantization: str = Field(pattern=r"^[A-Z0-9_]{2,24}$")
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
    config_url: str
    slot: dict
    setup_recipe: dict
    setup_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prepare_engine: StrictBool
    preparation_available: StrictBool
    prerequisite_budget_bytes: StrictInt | None = Field(default=None, ge=0, exclude_if=lambda v: v is None)
    preparation_notice: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid(self):
        if (
            self.id != "hub-image-" + self.file.sha256[:24]
            or len(self.file.urls) != 1
            or source_identity(self.file.urls[0]) != (self.repository, self.revision, self.filename)
            or parse_source(self.configuration_repository).repository != self.configuration_repository
            or self.source_url != f"https://huggingface.co/{self.repository}/tree/{self.revision}"
            or self.license_url != f"https://huggingface.co/{self.repository}/blob/{self.revision}/README.md"
            or self.config_url
            != f"https://huggingface.co/{self.configuration_repository}/resolve/{self.configuration_revision}/transformer/config.json"
            or self.slot.get("profile") != SLOT
            or self.slot.get("runtime_profile") != PROFILE
            or self.slot.get("role") != "diffusion"
            or self.setup_recipe.get("profile") != PROFILE
            or self.slot.get("runtime_image_reference") != self.setup_recipe.get("image_reference")
            or fingerprint(self.setup_recipe) != self.setup_manifest_sha256
            or {v.get("role") for v in self.setup_recipe.get("inputs", [])}
            != {"diffusion", "text_encoder", "vision_projector", "vae", "upscaler"}
        ):
            raise ValueError(
                "The image checkpoint must bind its pinned source and complete fixed runtime recipe"
            )
        return self


async def resolve_profile(observation, check):
    from app.image_setup_client import ImageSetupClient

    check()
    bases = observation.get("base_models", [])
    if not isinstance(bases, list) or len(bases) > 1 or not COMMIT.fullmatch(observation["revision"]):
        raise ValueError("An image checkpoint needs one immutable publisher configuration")
    repo = bases[0] if bases else observation["repository"]
    if parse_source(repo).repository != repo:
        raise ValueError("Choose a public HF base model repository")
    revision = "main" if bases else observation["revision"]
    meta = await metadata_json(f"https://huggingface.co/api/models/{repo}/revision/{revision}", check)
    if (
        not isinstance(meta, dict)
        or meta.get("id") != repo
        or meta.get("private") is True
        or not COMMIT.fullmatch(str(meta.get("sha", "")))
    ):
        raise ValueError("The image publisher configuration revision is unavailable")
    url = f"https://huggingface.co/{repo}/resolve/{meta['sha']}/transformer/config.json"
    config = await metadata_json(url, check)
    if not isinstance(config, dict) or any(
        type(config.get(k)) is not type(v) or config.get(k) != v for k, v in GEOMETRY.items()
    ):
        raise ValueError("This image graph needs its own compatible runtime slot")
    report = ImageSetupClient(timeout=20).runtime_setup_catalog()
    check()
    slots = [v for v in report.get("checkpoint_slots", []) if v.get("profile") == SLOT]
    if len(slots) != 1:
        raise ValueError("Update the Host Runner to inspect compatible image checkpoint slots")
    return {
        "source_repository": observation["repository"],
        "source_revision": observation["revision"],
        "configuration_repository": repo,
        "configuration_revision": meta["sha"],
        "configuration_sha256": fingerprint(config),
        "config_url": url,
        "slot": slots[0],
        "setup_recipe": report["recipe"],
        "setup_manifest_sha256": report["manifest_sha256"],
        "prepare_engine": (report.get("managed_images") or {}).get("available") is not True,
        "preparation_available": bool(
            (report.get("managed_images") or {}).get("available") is True
            or report.get("installation_available") is True
        ),
        "preparation_notice": (report.get("installation_notice") or "")[:500],
        "prerequisite_budget_bytes": prerequisite_budget(report),
    }


def candidate_from_profile(observation, filename):
    profile = dict(observation["image_profile"])
    if (profile.pop("source_repository"), profile.pop("source_revision")) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The image profile belongs to another immutable source")
    matches = [v for v in observation["files"] if v["filename"] == filename]
    if (
        len(matches) != 1
        or not matches[0].get("identity_available")
        or matches[0].get("format") != "gguf"
        or re.search(r"mmproj|projector|\d{5}-of-\d{5}\.gguf$", filename, re.I)
    ):
        raise ValueError("Choose one complete diffusion GGUF with a publisher SHA256")
    file = matches[0]
    quant = re.search(r"(?:^|[.-])((?:I?Q|BF|F)[0-9][A-Z0-9_]*)(?=\.gguf$)", filename.upper(), re.I)
    return HubImageCandidate(
        id="hub-image-" + file["sha256"][:24],
        name=observation["repository"].rsplit("/", 1)[-1][:180],
        filename=filename,
        quantization=quant.group(1).upper() if quant else "GGUF",
        file=FileSpec(sha256=file["sha256"], size_bytes=file["size_bytes"], urls=(file["source_url"],)),
        **{k: observation[k] for k in ("repository", "revision", "source_url", "license", "license_url")},
        **profile,
    )


def recommendation(entry, hardware):
    def valid(v):
        return type(v) in {int, float} and math.isfinite(v) and v > 0

    ram = (hardware.get("memory") or {}).get("total_mib")
    required_ram = max(12288, entry.file.size_bytes / 1024**2 + 2048)
    reference_mib = entry.slot["reference"]["size_bytes"] / 1024**2
    primary = max(12288, math.ceil(12288 + entry.file.size_bytes / 1024**2 - reference_mib))
    devices = sorted(
        (
            v
            for v in hardware.get("gpus", [])
            if isinstance(v, dict)
            and type(v.get("index")) is int
            and v["index"] >= 0
            and valid(v.get("memory_total_mib"))
        ),
        key=lambda v: (-v["memory_total_mib"], v["index"]),
    )
    selected = []
    if (
        hardware.get("container_gpu_ready") is not False
        and valid(ram)
        and ram >= required_ram
        and (hardware.get("host") or {}).get("system", "Linux") == "Linux"
    ):
        # Preserve the qualified two-device component placement; never pool VRAM.
        for gpu in devices:
            companion = next(
                (v for v in devices if v["index"] != gpu["index"] and v["memory_total_mib"] >= 12288), None
            )
            if gpu["memory_total_mib"] >= primary and companion:
                selected = [gpu["index"], companion["index"]]
                break
    return {
        "fits": bool(selected),
        "gpus": selected,
        "context_size": None,
        "reason": "Estimated image fit with fixed encoder/VAE companions; capacity assumes allocated GPUs are free"
        if selected
        else "This image profile needs sufficient RAM and two GPUs for its fixed component placement",
        "primary_vram_mib": primary,
        "companion_vram_mib": 12288,
        "ram_mib": math.ceil(required_ram),
        "maximum_side": 1024,
        "cpu_offload": False,
    }


def refresh_plan(entry, check):
    from app.image_setup_client import ImageSetupClient

    check()
    report = ImageSetupClient(timeout=20).runtime_setup_catalog()
    check()
    if report.get("manifest_sha256") != entry.setup_manifest_sha256 or entry.slot not in report.get(
        "checkpoint_slots", []
    ):
        raise ValueError("The supported image recipe changed; inspect its source again")
    return HubImageCandidate.model_validate(
        {
            **entry.model_dump(mode="json"),
            "prepare_engine": (report.get("managed_images") or {}).get("available") is not True,
            "preparation_available": bool(
                (report.get("managed_images") or {}).get("available") is True
                or report.get("installation_available") is True
            ),
            "preparation_notice": (report.get("installation_notice") or "")[:500],
            "prerequisite_budget_bytes": prerequisite_budget(report),
        }
    )


def prerequisite_budget(report):
    recipe = report["recipe"]
    total = sum(v["size_bytes"] for v in recipe["inputs"])
    cached = (report.get("storage") or {}).get("cached_model_bytes_estimate")
    cached = cached if type(cached) is int and 0 <= cached <= total else 0
    engine = (
        0
        if (report.get("image") or {}).get("present") is True
        else max(recipe.get("minimum_free_bytes", 0), recipe["download_bytes"])
    )
    return 0 if (report.get("managed_images") or {}).get("available") is True else total - cached + engine
