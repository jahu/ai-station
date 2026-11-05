"""Shared immutable-source/recipe contract for native SafeTensors model plans."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.hub_sources import parse_source
from app.model_download_files import FileSpec
from app.model_setup import fingerprint
from app.model_source_recovery import source_identity


class HubNativeCandidate(BaseModel):
    PREFIX: ClassVar[str]
    PROFILE: ClassVar[str]
    SLOT: ClassVar[str]
    ROLE: ClassVar[str]
    MODEL_FIELD: ClassVar[str]
    MODELS: ClassVar[frozenset[str]]
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: str
    id: str
    name: str = Field(min_length=1, max_length=180)
    capability: str
    runtime: str
    runtime_profile: None = None
    architecture: str
    quantization: str
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
    configuration_filename: Literal["safetensors-header"]
    config_url: str
    checkpoint_header: dict
    slot: dict
    setup_recipe: dict
    setup_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prepare_engine: StrictBool
    preparation_available: StrictBool
    host_profile_compatible: StrictBool
    prerequisite_budget_bytes: StrictInt = Field(ge=0)
    preparation_notice: str = Field(default="", max_length=500)
    component_licenses: list[dict] = Field(max_length=12)

    @model_validator(mode="after")
    def valid(self):
        if (
            self.id != self.PREFIX + self.file.sha256[:24]
            or len(self.file.urls) != 1
            or source_identity(self.file.urls[0]) != (self.repository, self.revision, self.filename)
            or parse_source(self.configuration_repository).repository != self.configuration_repository
            or self.source_url != f"https://huggingface.co/{self.repository}/tree/{self.revision}"
            or self.license_url != f"https://huggingface.co/{self.repository}/blob/{self.revision}/README.md"
            or self.config_url != self.file.urls[0]
            or self.configuration_repository != self.repository
            or self.configuration_revision != self.revision
            or self.configuration_sha256 != self.checkpoint_header.get("header_sha256")
            or self.checkpoint_header.get("schema_sha256") != self.slot.get("schema_sha256")
            or self.checkpoint_header.get("tensor_count") != self.slot.get("tensor_count")
            or not self.checkpoint_header.get("dtypes")
            or any(v not in self.slot.get("allowed_dtypes", []) for v in self.checkpoint_header["dtypes"])
            or self.slot.get("profile") != self.SLOT
            or self.slot.get("runtime_profile") != self.PROFILE
            or self.slot.get("role") != self.ROLE
            or self.setup_recipe.get("profile") != self.PROFILE
            or self.slot.get("runtime_manifest_sha256") != self.setup_manifest_sha256
            or fingerprint(self.setup_recipe) != self.setup_manifest_sha256
            or {
                v.get(self.MODEL_FIELD)
                for v in self.setup_recipe.get("inputs", [])
                if v.get("kind") == "model"
            }
            != self.MODELS
        ):
            raise ValueError(
                f"The {self.capability} checkpoint needs its pinned source and complete fixed runtime recipe"
            )
        return self
