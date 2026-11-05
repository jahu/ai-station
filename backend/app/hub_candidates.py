"""Server-resolved new GGUF plans; native inspection still verifies every hint."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

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
            or self.id != self.expected_id()
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

    def expected_id(self):
        return "hub-" + self.file.sha256[:24]


def download_candidate(payload):
    if payload.get("origin") == "hub_split":
        from app.hub_split_candidates import HubSplitCandidate

        return HubSplitCandidate.model_validate(payload)
    if payload.get("origin") == "hub_avatar":
        from app.hub_avatar_candidates import HubAvatarCandidate

        return HubAvatarCandidate.model_validate(payload)
    if payload.get("origin") == "hub_embedding":
        from app.hub_embedding_candidates import HubEmbeddingCandidate

        return HubEmbeddingCandidate.model_validate(payload)
    if payload.get("origin") == "hub_music":
        from app.hub_music_candidates import HubMusicCandidate

        return HubMusicCandidate.model_validate(payload)
    if payload.get("origin") == "hub_speech":
        from app.hub_speech_candidates import HubSpeechCandidate

        return HubSpeechCandidate.model_validate(payload)
    if payload.get("origin") == "hub_video":
        from app.hub_video_candidates import HubVideoCandidate

        return HubVideoCandidate.model_validate(payload)
    if payload.get("origin") == "hub_image":
        from app.hub_image_candidates import HubImageCandidate

        return HubImageCandidate.model_validate(payload)
    return (
        HubCandidate.model_validate(payload)
        if payload.get("origin") == "hub"
        else Candidate.model_validate(payload)
    )


def geometry(config, architecture=None):
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
    if architecture is None and isinstance(model_type, str):
        architecture = types.get(model_type)
    if architecture is None or not isinstance(model_type, str) or types.get(model_type) != architecture:
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


class LanguageProfile(BaseModel):
    """One immutable publisher configuration shared by compatible file variants."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_repository: str
    source_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    configuration_repository: str
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_url: str
    architecture: Literal["llama", "qwen2", "qwen3", "qwen35"]
    trained_context: StrictInt = Field(ge=4096, le=16777216)
    attention_layers: StrictInt = Field(ge=1, le=512)
    kv_heads: StrictInt = Field(ge=1, le=512)
    key_length: StrictInt = Field(ge=32, le=4096)
    value_length: StrictInt = Field(ge=32, le=4096)
    state_reserve_mib: StrictInt = Field(ge=0, le=4096)


async def resolve_profile(observation, check):
    check()
    if not isinstance(observation, dict) or not COMMIT.fullmatch(str(observation.get("revision", ""))):
        raise ValueError("Inspect an immutable model source first")
    architecture = observation.get("architecture_hint") or None
    if observation.get("pipeline_hint") not in {"", "text-generation"}:
        raise ValueError("This capability needs its own compatible recipe, not a language-model installation")
    if architecture not in {None, "llama", "qwen2", "qwen3", "qwen35"}:
        raise ValueError("This GGUF needs a supported architecture profile before installation")
    repository = parse_source(observation["repository"]).repository
    bases = observation.get("base_models", [])
    if not isinstance(bases, list) or len(bases) > 1:
        raise ValueError("Multiple base configurations require a compatible reviewed recipe")
    configuration_repository = bases[0] if bases else repository
    if parse_source(configuration_repository).repository != configuration_repository:
        raise ValueError("The configuration must name an HF model repository")
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
    return LanguageProfile(
        source_repository=repository,
        source_revision=observation["revision"],
        configuration_repository=configuration_repository,
        configuration_revision=configuration_revision,
        configuration_sha256=fingerprint(config),
        config_url=config_url,
        **dimensions,
    )


def candidate_from_profile(observation, filename, profile, *, context_ceiling=32768):
    profile = LanguageProfile.model_validate(profile)
    if (profile.source_repository, profile.source_revision) != (
        observation["repository"],
        observation["revision"],
    ):
        raise ValueError("The publisher profile belongs to another immutable source")
    selected = [f for f in observation["files"] if f["filename"] == filename]
    if len(selected) != 1 or not selected[0].get("identity_available") or selected[0].get("format") != "gguf":
        raise ValueError("Choose a GGUF with a publisher SHA256 and exact size")
    if re.search(r"mmproj|projector|\d{5}-of-\d{5}\.gguf$", filename, re.I):
        raise ValueError("Vision companions and split GGUFs need a complete compatible bundle plan")
    file = selected[0]
    quant = re.search(r"(?:^|[.-])((?:I?Q|BF|F)[0-9][A-Z0-9_]*)(?=\.gguf$)", filename.upper(), re.I)
    if type(context_ceiling) is not int or context_ceiling not in {32768, 131072}:
        raise ValueError("Choose a supported context target")
    ceiling = min(context_ceiling, (profile.trained_context // 256) * 256)
    fields = profile.model_dump(exclude={"source_repository", "source_revision"})
    return HubCandidate(
        id="hub-" + file["sha256"][:24],
        name=observation["repository"].rsplit("/", 1)[-1][:180],
        quantization=quant.group(1).upper() if quant else "GGUF",
        filename=filename,
        file=FileSpec(sha256=file["sha256"], size_bytes=file["size_bytes"], urls=(file["source_url"],)),
        repository=observation["repository"],
        revision=observation["revision"],
        license=observation["license"],
        source_url=observation["source_url"],
        license_url=observation["license_url"],
        context_ceiling=ceiling,
        **fields,
    )


async def resolve_candidate(observation, filename, check, context_ceiling=131072):
    selected_file = next((f for f in observation["files"] if f["filename"] == filename), None)
    from app.hub_model_parts import looks_split

    if selected_file and selected_file.get("format") == "gguf" and looks_split(filename):
        from app.hub_split_candidates import INSTALLATION_QUALIFIED
        from app.hub_split_candidates import candidate_from_profile as split_candidate

        if not INSTALLATION_QUALIFIED:
            raise ValueError("Split GGUFs need a complete compatible bundle plan")
        profile = observation.get("language_profile")
        if not profile:
            raise ValueError(
                "Split GGUFs need a complete compatible bundle plan and pinned language profile; inspect the source again"
            )
        check()
        return split_candidate(observation, filename, profile, context_ceiling=context_ceiling)
    if selected_file and selected_file.get("format") in {"pth", "pt", "bin"}:
        from app.hub_avatar_candidates import candidate_from_profile as avatar_candidate
        from app.hub_avatar_candidates import refresh_plan
        from app.hub_avatar_candidates import resolve_profile as avatar_profile

        profile = observation.get("avatar_profile") or await avatar_profile(observation, check, filename)
        return refresh_plan(avatar_candidate({**observation, "avatar_profile": profile}, filename), check)
    if selected_file and selected_file.get("format") == "onnx":
        from app.hub_embedding_candidates import candidate_from_profile as embedding_candidate
        from app.hub_embedding_candidates import resolve_profile as embedding_profile

        profile = observation.get("embedding_profile") or await embedding_profile(observation, check)
        return embedding_candidate({**observation, "embedding_profile": profile}, filename)
    if selected_file and selected_file.get("format") == "safetensors":
        from app.hub_native_profiles import candidate

        return await candidate(observation, filename, check)
    if observation.get("image_profile"):
        from app.hub_image_candidates import candidate_from_profile as image_candidate
        from app.hub_image_candidates import refresh_plan

        return refresh_plan(image_candidate(observation, filename), check)
    # Old accepted requests retain their original context target. New requests
    # explicitly record their balanced or longer-context target.
    if observation.get("language_profile"):
        check()
        return candidate_from_profile(
            observation, filename, observation["language_profile"], context_ceiling=context_ceiling
        )
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

    profile = await resolve_profile(inspected, check)
    return candidate_from_profile(inspected, filename, profile, context_ceiling=context_ceiling)
