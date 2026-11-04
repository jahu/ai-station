"""Server-resolved new GGUF plans; native inspection still verifies every hint."""

import re
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from app.hub_sources import COMMIT, HubSource, inspect_source, metadata_json, parse_source
from app.model_download_files import FileSpec
from app.model_setup import fingerprint
from app.model_source_recovery import source_identity
from app.setup_models import Candidate


class HubCandidate(Candidate):
    origin: Literal["hub"] = "hub"
    architecture: Literal["llama", "qwen2", "qwen3", "qwen35"]
    quantization: str = Field(pattern=r"^[A-Z0-9_]{2,24}$")
    license: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=180)
    filename: str = Field(min_length=1, max_length=400)
    # GPU-only admission here. Explicit CPU recipes keep their existing authority.
    runtime_profile: None = None
    trained_context: StrictInt = Field(ge=512, le=16777216)
    attention_layers: StrictInt = Field(ge=1, le=512)
    kv_heads: StrictInt = Field(ge=1, le=512)
    key_length: StrictInt = Field(ge=32, le=4096)
    value_length: StrictInt = Field(ge=32, le=4096)
    configuration_repository: str
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def pinned_hub_identity(self):
        if (
            len(self.file.urls) != 1
            or source_identity(self.file.urls[0]) != (self.repository, self.revision, self.filename)
            or self.id != "hub-" + self.file.sha256[:24]
            or self.key_length % 32
            or self.value_length % 32
            or self.state_reserve_mib != (512 if self.architecture == "qwen35" else 0)
            or self.config_url
            != f"https://huggingface.co/{self.configuration_repository}/resolve/{self.configuration_revision}/config.json"
            or self.context_ceiling > self.trained_context
            or self.source_url != f"https://huggingface.co/{self.repository}/tree/{self.revision}"
            or self.license_url != f"https://huggingface.co/{self.repository}/blob/{self.revision}/README.md"
        ):
            raise ValueError("The resolved GGUF plan identity or attention profile is inconsistent")
        if parse_source(self.configuration_repository).repository != self.configuration_repository:
            raise ValueError("The configuration must name an HF model repository")
        per_token = self.attention_layers * self.kv_heads * ((self.key_length + self.value_length) // 32) * 34
        if per_token > 16 * 1024**2:
            raise ValueError("Attention geometry exceeds the supported estimator")
        return self


def download_candidate(payload):
    return (
        HubCandidate.model_validate(payload)
        if payload.get("origin") == "hub"
        else Candidate.model_validate(payload)
    )


def geometry(config, architecture):
    if not isinstance(config, dict):
        raise ValueError("Publisher configuration must be a JSON object")
    text = config.get("text_config", config)
    if not isinstance(text, dict):
        raise ValueError("Publisher text configuration is unavailable")
    types = {
        "llama": "llama",
        "mistral": "llama",
        "qwen2": "qwen2",
        "qwen3": "qwen3",
        "qwen3_5": "qwen35",
        "qwen3_5_text": "qwen35",
    }
    model_type = text.get("model_type", config.get("model_type"))
    if not isinstance(model_type, str) or types.get(model_type) != architecture:
        raise ValueError("This architecture has no matching supported llama.cpp planning profile")
    causal_classes = {
        "llama": {"LlamaForCausalLM", "MistralForCausalLM"},
        "qwen2": {"Qwen2ForCausalLM"},
        "qwen3": {"Qwen3ForCausalLM"},
        "qwen35": {"Qwen3_5ForCausalLM", "Qwen3_5ForConditionalGeneration"},
    }
    classes = text.get("architectures") or config.get("architectures")
    if (
        not isinstance(classes, list)
        or len(classes) != 1
        or not isinstance(classes[0], str)
        or classes[0] not in causal_classes[architecture]
    ):
        raise ValueError("This configuration does not declare a supported causal language model")

    def positive(key, maximum, default=None):
        value = text.get(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"Publisher configuration needs valid {key}")
        return value

    layers = positive("num_hidden_layers", 512)
    heads = positive("num_attention_heads", 512)
    embedding = positive("hidden_size", 1048576)
    kv = positive("num_key_value_heads", heads, heads)
    key = positive("head_dim", 4096, embedding // heads)
    value = positive("value_head_dim", 4096, key)
    context = positive("max_position_embeddings", 16777216)
    if architecture == "qwen35":
        interval = positive("full_attention_interval", layers)
        layers //= interval
    return {
        "architecture": architecture,
        "trained_context": context,
        "attention_layers": layers,
        "kv_heads": kv,
        "key_length": key,
        "value_length": value,
        "state_reserve_mib": 512 if architecture == "qwen35" else 0,
    }


async def resolve_candidate(observation, filename, check):
    if not isinstance(observation, dict) or not COMMIT.fullmatch(str(observation.get("revision", ""))):
        raise ValueError("Inspect an immutable model source first")
    repository = parse_source(observation.get("repository", "")).repository
    selected = [f for f in observation.get("files", []) if f.get("filename") == filename]
    if len(selected) != 1 or not selected[0].get("identity_available") or selected[0].get("format") != "gguf":
        raise ValueError("Choose a GGUF with a publisher SHA256 and exact size")
    if re.search(r"mmproj|projector|\d{5}-of-\d{5}\.gguf$", filename, re.I):
        raise ValueError("Vision companions and split GGUFs need a complete compatible bundle plan")
    # Refresh only the immutable observation, never a moving branch or another hash.
    inspected = await inspect_source(
        HubSource(repository=repository, revision=observation["revision"], filename=filename), check
    )
    file = inspected["files"][0]
    if any(file.get(k) != selected[0].get(k) for k in ("filename", "sha256", "size_bytes")):
        raise ValueError("The selected publisher object identity changed")
    architecture = inspected["architecture_hint"]
    if inspected.get("pipeline_hint") not in {"", "text-generation"}:
        raise ValueError("This capability needs its own compatible recipe, not a language-model installation")
    if architecture not in {"llama", "qwen2", "qwen3", "qwen35"}:
        raise ValueError("This GGUF needs a supported architecture profile before installation")
    bases = inspected["base_models"]
    if len(bases) > 1:
        raise ValueError("Multiple base configurations require a compatible reviewed recipe")
    configuration_repository = bases[0] if bases else repository
    revision = "main" if bases else observation["revision"]
    meta = await metadata_json(
        f"https://huggingface.co/api/models/{configuration_repository}/revision/{revision}", check
    )
    if (
        not isinstance(meta, dict)
        or meta.get("id") != configuration_repository
        or meta.get("private") is True
        or not COMMIT.fullmatch(str(meta.get("sha", "")))
    ):
        raise ValueError("The publisher configuration revision could not be resolved")
    configuration_revision = meta["sha"]
    config_url = (
        f"https://huggingface.co/{configuration_repository}/resolve/{configuration_revision}/config.json"
    )
    config = await metadata_json(config_url, check)
    dimensions = geometry(config, architecture)
    quant = re.search(r"(?:^|[.-])((?:I?Q|BF|F)[0-9][A-Z0-9_]*)(?=\.gguf$)", filename.upper(), re.I)
    ceiling = min(131072, (dimensions["trained_context"] // 256) * 256)
    if ceiling < 4096:
        raise ValueError("This model cannot provide the minimum supported 4096-token GPU context")
    return HubCandidate(
        id="hub-" + file["sha256"][:24],
        name=repository.rsplit("/", 1)[-1][:180],
        quantization=quant.group(1).upper() if quant else "GGUF",
        filename=filename,
        file=FileSpec(sha256=file["sha256"], size_bytes=file["size_bytes"], urls=(file["source_url"],)),
        repository=repository,
        revision=observation["revision"],
        license=inspected["license"],
        source_url=inspected["source_url"],
        license_url=inspected["license_url"],
        config_url=config_url,
        configuration_repository=configuration_repository,
        configuration_revision=configuration_revision,
        configuration_sha256=fingerprint(config),
        context_ceiling=ceiling,
        **dimensions,
    )
