"""Declarative motion graphics. No caller-supplied HTML, CSS, JS or asset paths."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.media_inputs import MediaInput


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=140)]


class Style(Fields):
    palette: list[Color] = Field(min_length=1, max_length=8)
    typography: Literal["sans", "humanist", "editorial", "mono"] = "sans"
    motion: Literal["gentle", "dynamic", "minimal"] = "gentle"
    brand: str = Field(default="", max_length=160)


class Metric(Fields):
    value: str = Field(min_length=1, max_length=28)
    label: str = Field(min_length=1, max_length=100)


class Scene(Fields):
    layout: Literal["title", "statement", "split", "steps", "quote", "metrics", "closing", "full_bleed"] = (
        "statement"
    )
    duration_frames: StrictInt = Field(ge=30, le=2700)
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=140)
    body: str = Field(default="", max_length=420)
    points: list[ShortText] = Field(default_factory=list, max_length=5)
    metrics: list[Metric] = Field(default_factory=list, max_length=3)
    media: UUID | None = None
    media_fit: Literal["contain", "cover"] = "contain"
    media_motion: Literal["auto", "hold", "push_in", "pull_out", "pan_left", "pan_right", "rise"] = "auto"
    media_start_seconds: float = Field(default=0.0, ge=0, le=600, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def complete(self):
        if not (self.title or self.body or self.points or self.metrics or self.media):
            raise ValueError("Every scene needs content")
        if self.layout == "metrics" and not self.metrics:
            raise ValueError("A metrics scene needs actual values and labels")
        if self.layout == "steps" and not self.points:
            raise ValueError("A steps scene needs its actual steps")
        if self.layout == "full_bleed" and self.media is None:
            raise ValueError("A full-frame visual scene needs actual media")
        return self


class Composition(Fields):
    width: Literal[1080, 1920] = 1080
    height: Literal[1080, 1920] = 1920
    fps: Literal[30] = 30
    style: Style
    scenes: list[Scene] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def bounded(self):
        if (self.width, self.height) not in {(1080, 1920), (1920, 1080), (1080, 1080)}:
            raise ValueError("Choose a full-HD portrait, landscape or square canvas")
        if self.frames > 30 * 600:
            raise ValueError("Keep one material within ten minutes")
        return self

    @property
    def frames(self):
        return sum(scene.duration_frames for scene in self.scenes)


class Source(MediaInput):
    artifact_id: UUID
    kind: Literal["image", "video", "audio"]


RENDER_RAM_MIB = 4096
SUPERVISOR_RAM_MIB = 256
RAM_MIB = RENDER_RAM_MIB + SUPERVISOR_RAM_MIB


class MotionRequest(Fields):
    run_id: UUID
    deadline_at: float = Field(gt=0, strict=True, allow_inf_nan=False)
    composition: Composition
    sources: list[Source] = Field(default_factory=list, max_length=61)
    audio_artifact_id: UUID | None = None
    observation: str = Field(pattern=r"^[a-f0-9]{64}$")
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def bindings(self):
        if set(self.permissions) != {"filesystem_read", "workspace_write"}:
            raise ValueError("Motion rendering requires artifact read/write permissions")
        sources = {s.artifact_id: s for s in self.sources}
        wanted = {scene.media for scene in self.composition.scenes if scene.media}
        if self.audio_artifact_id:
            wanted.add(self.audio_artifact_id)
        if len(sources) != len(self.sources) or set(sources) != wanted:
            raise ValueError("Bind exactly the selected owned media")
        for scene in self.composition.scenes:
            if scene.media and sources[scene.media].kind not in {"image", "video"}:
                raise ValueError("Scene visuals require an inspected image or video")
        if self.audio_artifact_id and sources[self.audio_artifact_id].kind != "audio":
            raise ValueError("The final mix must be inspected audio")
        if sum(source.size_bytes for source in self.sources) > 2 * 1024**3:
            raise ValueError("Keep one material's source assets within two GiB")
        return self
