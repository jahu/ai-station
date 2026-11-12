"""Editorial intent, separate from executable renderer composition and runtime settings."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.creative_projects import Defaults
from app.creative_sessions import Fields


class NarrationWords(Fields):
    minimum: StrictInt | None = Field(default=None, ge=1, le=3000, exclude_if=lambda v: v is None)
    maximum: StrictInt | None = Field(default=None, ge=1, le=3000, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("Choose at least one spoken word limit")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum spoken words cannot exceed the maximum")
        return self


class StudioOptions(Defaults):
    narration_words: NarrationWords | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def narrated(self):
        if self.narration_words and self.audio not in {"voice", "voice_music"}:
            raise ValueError("Spoken word limits require narration")
        return self


def narration_word_count(storyboard):
    # Whitespace-delimited words/numbers; punctuation-only tokens do not count.
    return sum(any(c.isalnum() for c in word) for s in storyboard.scenes for word in s.narration.split())


def validate_narration_words(storyboard, options):
    limits = StudioOptions.model_validate(options).narration_words
    if limits is None:
        return
    count = narration_word_count(storyboard)
    if limits.minimum is not None and count < limits.minimum:
        raise ValueError(
            f"Narration contains {count} spoken words; at least {limits.minimum} were requested. Expand the actual spoken script, not captions or acting directions."
        )
    if limits.maximum is not None and count > limits.maximum:
        raise ValueError(
            f"Narration contains {count} spoken words; at most {limits.maximum} were requested. Revise the actual spoken script without cutting audio later."
        )


class NarrationDelivery(Fields):
    direction: Literal[
        "natural", "whisper", "happy", "sad", "afraid", "angry", "calm", "excited", "breathy", "sighing"
    ] = "natural"
    pace: Literal["natural", "slow", "fast"] = "natural"


class Shot(Fields):
    purpose: str = Field(min_length=1, max_length=500)
    duration_frames: StrictInt = Field(ge=30, le=2700)
    visual_kind: Literal["image", "video", "library", "graphics", "reuse"]
    reuse_scene: StrictInt | None = Field(default=None, ge=0, le=59, exclude_if=lambda value: value is None)
    visual_brief: str = Field(default="", max_length=2400)
    framing: str = Field(default="", max_length=500)
    source_artifact_id: UUID | None = None
    reference_artifact_ids: list[UUID] = Field(default_factory=list, max_length=4)
    layout: Literal["title", "statement", "split", "steps", "quote", "closing", "full_bleed"] = "full_bleed"
    title: str = Field(default="", max_length=140)
    eyebrow: str = Field(default="", max_length=80)
    body: str = Field(default="", max_length=420)
    points: list[str] = Field(default_factory=list, max_length=5)
    narration: str = Field(default="", max_length=1000)
    media_motion: Literal["auto", "hold", "push_in", "pull_out", "pan_left", "pan_right", "rise"] = "auto"
    media_fit: Literal["contain", "cover"] = "cover"
    media_start_seconds: float = Field(default=0.0, ge=0, le=600, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def usable(self):
        if (self.visual_kind == "reuse") != (self.reuse_scene is not None):
            raise ValueError("A shared visual needs its earlier source scene; other kinds cannot select one")
        if self.visual_kind == "reuse" and self.reference_artifact_ids:
            raise ValueError("A shared scene uses its original visual, not new generation references")
        if self.visual_kind == "library" and self.source_artifact_id is None:
            raise ValueError("A Library shot needs its selected source")
        if self.visual_kind != "library" and self.source_artifact_id is not None:
            raise ValueError("Generated shots cannot masquerade as completed Library media")
        if self.visual_kind in {"image", "video"} and not self.visual_brief:
            raise ValueError("Generated visuals need a concrete shot brief")
        if self.visual_kind == "graphics" and (
            not (self.title or self.body or self.points) or self.layout == "full_bleed"
        ):
            raise ValueError("An editorial graphics shot needs content and a suitable layout")
        if self.layout == "steps" and not self.points:
            raise ValueError("A steps shot needs its actual steps")
        if len(set(self.reference_artifact_ids)) != len(self.reference_artifact_ids):
            raise ValueError("Choose each reference once")
        if any(not 1 <= len(p) <= 140 for p in self.points):
            raise ValueError("Keep on-screen points brief")
        return self


class Storyboard(Fields):
    title: str = Field(min_length=1, max_length=160)
    concept: str = Field(min_length=1, max_length=2000)
    hook: str = Field(min_length=1, max_length=1000)
    audio: Literal["voice_music", "voice", "music", "silent"]
    voice_direction: str = Field(default="", max_length=1000)
    narration_delivery: NarrationDelivery = Field(default_factory=NarrationDelivery)
    music_brief: str = Field(default="", max_length=2000)
    scenes: list[Shot] = Field(min_length=1, max_length=60)

    @property
    def frames(self):
        return sum(shot.duration_frames for shot in self.scenes)

    @model_validator(mode="after")
    def complete(self):
        for index, shot in enumerate(self.scenes):
            if shot.visual_kind == "reuse":
                if shot.reuse_scene >= index:
                    raise ValueError(
                        "A shared visual must reference an earlier scene, never itself or a future scene"
                    )
                if self.scenes[shot.reuse_scene].visual_kind == "graphics":
                    raise ValueError(
                        "Share an image, video or Library visual, not an editorial graphics scene"
                    )
        if self.frames > 18000:
            raise ValueError("Keep one material within ten minutes")
        voice = self.audio in {"voice", "voice_music"}
        if voice and not any(s.narration for s in self.scenes):
            raise ValueError("Narrated material needs an actual script")
        if not voice and any(s.narration for s in self.scenes):
            raise ValueError("The storyboard must preserve the chosen audio policy")
        if self.audio in {"music", "voice_music"} and not self.music_brief:
            raise ValueError("Music needs a direction matching the edit")
        return self


class Create(Fields):
    client_request_id: UUID
    title: str = Field(default="Untitled material", min_length=1, max_length=160)
    brief: str = Field(min_length=1, max_length=12000)
    creative_project_id: UUID | None = None
    options: StudioOptions | None = None


class Update(Fields):
    expected_version: StrictInt = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    brief: str | None = Field(default=None, min_length=1, max_length=12000)
    options: StudioOptions | None = None
    archived: bool | None = None


class SaveRevision(Fields):
    client_request_id: UUID
    expected_version: StrictInt = Field(ge=1)
    parent_revision_id: UUID | None = None
    storyboard: Storyboard


class PlanRequest(Fields):
    client_request_id: UUID
    expected_version: StrictInt = Field(ge=1)
    model: str = Field(min_length=1, max_length=200)
    parent_revision_id: UUID | None = None
    feedback: str = Field(default="", max_length=8000)
    reference_artifact_ids: list[UUID] = Field(default_factory=list, max_length=12)
