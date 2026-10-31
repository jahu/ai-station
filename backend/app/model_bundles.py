"""Reviewed companion files; a verified bundle is not an installed runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.model_download_files import FileSpec


class BundleFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    file: FileSpec


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    name: str = Field(min_length=1, max_length=120)
    capability: Literal["speech", "image", "music", "video", "avatar"] = "speech"
    family: Literal["chatterbox", "qwen_image21", "ace_step15", "wan22", "sonic"] = "chatterbox"
    license: Literal["MIT", "Qwen Research", "Apache-2.0", "Multiple component licenses"] = "MIT"
    license_url: str
    source_url: str
    repository: str
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    files: tuple[BundleFile, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_objects(self):
        if len({item.filename for item in self.files}) != len(self.files) or len(
            {item.file.sha256 for item in self.files}
        ) != len(self.files):
            raise ValueError("Bundle filenames and file identities must be unique")
        return self

    @property
    def size_bytes(self):
        return sum(item.file.size_bytes for item in self.files)


REPOSITORY = "ResembleAI/chatterbox"
REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"


def _file(name, size, sha):
    return BundleFile(
        filename=name,
        file=FileSpec(
            size_bytes=size,
            sha256=sha,
            urls=(f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}",),
        ),
    )


BUNDLES = (
    Bundle(
        id="chatterbox-multilingual-v3-weights-v1",
        name="Chatterbox Multilingual · v3 model files",
        license_url=f"https://huggingface.co/{REPOSITORY}/blob/{REVISION}/README.md",
        source_url=f"https://huggingface.co/{REPOSITORY}/tree/{REVISION}",
        repository=REPOSITORY,
        revision=REVISION,
        files=(
            _file("ve.pt", 5698626, "4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1"),
            _file(
                "t3_mtl23ls_v3.safetensors",
                2143989928,
                "5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953",
            ),
            _file("s3gen.pt", 1057165844, "9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3"),
            _file(
                "grapheme_mtl_merged_expanded_v1.json",
                69989,
                "69632f47220a788a52ce2661d096453c5655e9bf25289d89a8d832c46ee07dbf",
            ),
            _file("conds.pt", 107374, "6552d70568833628ba019c6b03459e77fe71ca197d5c560cef9411bee9d87f4e"),
            _file(
                "Cangjie5_TC.json",
                1920163,
                "7073fd9de919443ae88e0bd2449917a65fe54898a4413ed1edcc4b67f28bce8c",
            ),
        ),
    ),
)


def bundle(identity):
    return next((item for item in BUNDLES if item.id == identity), None)
