"""Native bounded manifest and frozen source authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from ai_station_runner.media_inputs import MediaInput


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Placement(Fields):
    artifact_id: UUID
    start_frame: StrictInt = Field(default=0, ge=0, le=7499)
    gain: float = Field(default=1.0, ge=0, le=4, allow_inf_nan=False, strict=True)
    muted: StrictBool = False
    fade_in_frames: StrictInt = Field(default=0, ge=0, le=7500)
    fade_out_frames: StrictInt = Field(default=0, ge=0, le=7500)


class VideoClip(Placement):
    in_frame: StrictInt = Field(default=0, ge=0, le=7499)
    out_frame: StrictInt = Field(ge=1, le=7500)

    @model_validator(mode="after")
    def interval(self):
        if self.out_frame <= self.in_frame:
            raise ValueError("Clip end must follow its start")
        return self


class AudioTrack(Placement):
    in_sample: StrictInt = Field(default=0, ge=0, le=96000 * 300 - 1)
    duration_frames: StrictInt = Field(ge=1, le=7500)


class Manifest(Fields):
    fps: Literal[24, 25] = 24
    width: StrictInt = Field(default=1280, ge=128, le=1280, multiple_of=32)
    height: StrictInt = Field(default=704, ge=128, le=1280, multiple_of=32)
    clips: list[VideoClip] = Field(default_factory=list, max_length=16)
    tracks: list[AudioTrack] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def bounded(self):
        if self.width * self.height > 1280 * 704 or not (self.clips or self.tracks):
            raise ValueError("Choose a bounded film size and at least one media source")
        return self


def duration(clip, fps, source):
    return ((clip.out_frame - clip.in_frame) * fps + source["fps"] - 1) // source["fps"]


def inspect_manifest(manifest, sources):
    """Only inspected source observations can establish clip duration/authority."""
    intervals, end = [], 0
    for clip in manifest.clips:
        source = sources.get(str(clip.artifact_id), {})
        if source.get("kind") != "video" or clip.out_frame > source["frames"]:
            raise ValueError("Clip trim exceeds the inspected video")
        count = duration(clip, manifest.fps, source)
        if clip.fade_in_frames + clip.fade_out_frames > count:
            raise ValueError("Clip audio fades exceed its duration")
        intervals.append((clip.start_frame, clip.start_frame + count))
        end = max(end, clip.start_frame + count)
    ordered = sorted(intervals)
    if any(first[1] > second[0] for first, second in zip(ordered, ordered[1:])):
        raise ValueError("Video clips overlap; move or trim the clips")
    for track in manifest.tracks:
        source = sources.get(str(track.artifact_id), {})
        if source.get("kind") != "audio" or track.in_sample >= source["samples"]:
            raise ValueError("Choose an inspected WAV interval")
        required = (track.duration_frames * source["sample_rate"] + manifest.fps - 1) // manifest.fps
        # A final partial frame is padded explicitly, never truncating a source.
        padding = (source["sample_rate"] + manifest.fps - 1) // manifest.fps
        if track.in_sample + required > source["samples"] + padding - 1:
            raise ValueError("Audio trim exceeds its source")
        if track.fade_in_frames + track.fade_out_frames > track.duration_frames:
            raise ValueError("Audio fades exceed the track duration")
        end = max(end, track.start_frame + track.duration_frames)
    if not 1 <= end <= manifest.fps * 300:
        raise ValueError("Keep the complete timeline within five minutes")
    return end


RAM_MIB = 4096


class VideoSource(MediaInput):
    kind: Literal["video"]
    artifact_id: UUID
    frames: StrictInt = Field(ge=1, le=7500)
    fps: Literal[24, 25]
    width: StrictInt = Field(ge=128, le=1280, multiple_of=32)
    height: StrictInt = Field(ge=128, le=1280, multiple_of=32)

    @model_validator(mode="after")
    def bounded(self):
        if self.frames > self.fps * 300 or self.width * self.height > 1280 * 704:
            raise ValueError("Source exceeds the bounded video profile")
        return self


class AudioSource(MediaInput):
    kind: Literal["audio"]
    artifact_id: UUID
    samples: StrictInt = Field(ge=1, le=96000 * 300)
    sample_rate: StrictInt = Field(ge=8000, le=96000)
    channels: Literal[1, 2]
    sample_width: Literal[1, 2, 3, 4]

    @model_validator(mode="after")
    def bounded(self):
        if self.samples > self.sample_rate * 300 or self.size_bytes > 64 * 1024**2:
            raise ValueError("Source exceeds the bounded WAV profile")
        return self


class TimelineRequest(Fields):
    run_id: UUID
    deadline_at: float = Field(gt=0, strict=True, allow_inf_nan=False)
    manifest: Manifest
    sources: list[Annotated[VideoSource | AudioSource, Field(discriminator="kind")]] = Field(
        min_length=1, max_length=32
    )
    observation: str = Field(pattern=r"^[a-f0-9]{64}$")
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def bindings(self):
        values = {str(s.artifact_id): s.model_dump(mode="json") for s in self.sources}
        wanted = {str(p.artifact_id) for p in [*self.manifest.clips, *self.manifest.tracks]}
        if len(values) != len(self.sources) or wanted != set(values):
            raise ValueError("Bind exactly the selected timeline sources")
        if (
            sum(s.size_bytes for s in self.sources) > 8 * 1024**3
            or sum(s.size_bytes for s in self.sources if s.kind == "audio") > 512 * 1024**2
        ):
            raise ValueError("Timeline source bytes exceed the fixed profile")
        inspect_manifest(self.manifest, values)
        return self
