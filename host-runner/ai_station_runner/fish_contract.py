"""Frozen offline S2 Pro profile and bounded native request; no model imports."""

import hashlib
import io
import json
import wave
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.security import resolve_child
from ai_station_runner.transcription_protocol import audio_bytes

PROFILE = "fish_s2_bf16_dual_v1"
RAM_MIB = 24576
PRIMARY_VRAM_MIB = 10240
CODEC_VRAM_MIB = 5120
SOURCE_SHA256 = "00e6ece667bb971044525461412c04296a2a24d55bf6cedf9482b10e72eaa09e"
DIRECTIONS = {
    "natural": "",
    "whisper": "[whispering]",
    "happy": "[happy]",
    "sad": "[sad]",
    "afraid": "[scared]",
    "angry": "[angry]",
    "calm": "[calm]",
    "excited": "[excited]",
    "breathy": "[breathy]",
    "sighing": "[sighing]",
}
Direction = Literal[
    "natural", "whisper", "happy", "sad", "afraid", "angry", "calm", "excited", "breathy", "sighing"
]
Pace = Literal["natural", "slow", "fast"]
WRAPPERS = (
    "fish_contract.py",
    "fish_job.py",
    "memory_scope.py",
    "speech_chunks.py",
    "media_inputs.py",
    "security.py",
    "transcription_protocol.py",
    "recordings.py",
)
MODEL_FILES = {
    "chat_template.jinja": {
        "size": 4116,
        "sha256": "87a2728cb8dc9fe424d624542f6060ec05a1d285ebbec578bb078900e33396b5",
    },
    "codec.pth": {
        "size": 1871099728,
        "sha256": "74fc41c5a7151c6f350af8bd7e5d6e3accfcc7f3dfbfac23afd35af07052bb2f",
    },
    "config.json": {
        "size": 1863,
        "sha256": "261b519a2a9576710fc8533a77297fae007f0e7b3aa28a217f8352b7f32fe993",
    },
    "model-00001-of-00002.safetensors": {
        "size": 4986872984,
        "sha256": "c4218e8ac93be83b35eee30b4f94cb2e9b5ecff40f3e21611438d2f4f8804aad",
    },
    "model-00002-of-00002.safetensors": {
        "size": 4136876104,
        "sha256": "76738d23465deaac431433232c0762908cc99a6eddc3d49f67307d92680827be",
    },
    "model.safetensors.index.json": {
        "size": 32686,
        "sha256": "c8cb9974d3d17663a95dba1d6c3ea531fc42d377c0dff946f3a01a0ec48d45a3",
    },
    "special_tokens_map.json": {
        "size": 101864,
        "sha256": "c2ff18fde6e43b7408435bc8ed079af74531befba549358a97cbc59ce606bc6b",
    },
    "tokenizer.json": {
        "size": 12217872,
        "sha256": "f24e08099d45a8adf3f52f5f0b03276e433bb9d689bb15fcbcc48ce58744588b",
    },
    "tokenizer_config.json": {
        "size": 860832,
        "sha256": "b8d149343ae425b0da67e6708686aceb51be7815d9792f265fc12ff04d5e9856",
    },
}


class FishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    direction: Direction = "natural"
    pace: Pace = "natural"
    reference: MediaInput
    reference_text: str = Field(min_length=1, max_length=8000)
    observation: str = Field(pattern=r"^[a-f0-9]{64}$")
    gpus: list[StrictInt] = Field(min_length=2, max_length=2)
    deadline_at: float = Field(gt=0, strict=True, allow_inf_nan=False)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def distinct_devices(self):
        if len(set(self.gpus)) != 2 or any(gpu < 0 for gpu in self.gpus):
            raise ValueError("Fish requires two distinct allocated GPU indexes")
        return self


def direct(root, relative):
    path = resolve_child(Path(root), relative)
    if path != Path(root) / relative or not path.is_file():
        raise ValueError("Fish files must be direct configured files without symlinks")
    return path


def source_files(runtime):
    root = Path(runtime)
    if any(p.is_symlink() for p in (root / "fish_speech").rglob("*")):
        raise ValueError("Fish imports must not traverse symlinks")
    files = sorted(
        [*(root / "fish_speech").rglob("*.py"), *(root / "fish_speech/configs").rglob("*.yaml")],
        key=lambda p: p.relative_to(root).as_posix(),
    )
    if not files or len(files) > 1000:
        raise ValueError("Invalid Fish source tree")
    return [direct(root, p.relative_to(root).as_posix()) for p in files]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024**2), b""):
            value.update(block)
    return value.hexdigest()


def installation_signature(runtime, models):
    files = [
        *source_files(runtime),
        *(direct(models, name) for name in MODEL_FILES),
        *(direct(Path(__file__).parent, name) for name in WRAPPERS),
    ]
    return tuple(
        (
            str(p),
            p.stat().st_dev,
            p.stat().st_ino,
            p.stat().st_size,
            p.stat().st_mtime_ns,
            p.stat().st_ctime_ns,
        )
        for p in files
    )


def installation_observation(runtime, models):
    source = hashlib.sha256()
    for path in source_files(runtime):
        name = path.relative_to(runtime).as_posix().encode()
        source.update(len(name).to_bytes(4, "big"))
        source.update(name)
        source.update(bytes.fromhex(digest(path)))
    if source.hexdigest() != SOURCE_SHA256:
        raise ValueError("Fish source differs from the qualified revision")
    for name, expected in MODEL_FILES.items():
        path = direct(models, name)
        if path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
            raise ValueError("Fish model differs from the qualified publisher files")
    wrappers = {name: digest(direct(Path(__file__).parent, name)) for name in WRAPPERS}
    return hashlib.sha256(
        json.dumps(
            {
                "profile": PROFILE,
                "source": SOURCE_SHA256,
                "models": MODEL_FILES,
                "implementation": wrappers,
                "ram_mib": RAM_MIB,
                "gpus": 2,
                "context": 4096,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def reference_bytes(root, reference):
    relative = reference["relative_path"]
    if not relative.startswith("artifacts/") or resolve_child(root, relative) != root / relative:
        raise ValueError("Fish reference must be a direct owned artifact")
    data = audio_bytes(root, reference)
    with wave.open(io.BytesIO(data), "rb") as wav:
        if not 0.1 <= wav.getnframes() / wav.getframerate() <= 60:
            raise ValueError("Use a voice reference of 0.1–60 seconds")
    return data
