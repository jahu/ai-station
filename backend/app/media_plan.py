"""Exact, bounded segmented-media timeline; independent of the executor/queue."""

import hashlib
from fractions import Fraction

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    index: StrictInt = Field(ge=0)
    start_frame: StrictInt = Field(ge=0)
    first_frame: StrictInt = Field(default=0, ge=0, le=17)
    output_frames: StrictInt = Field(ge=1, le=81)
    generated_frames: StrictInt = Field(ge=17, le=81)
    seed: StrictInt = Field(ge=0, le=2147483647)


class MediaTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fps: StrictInt = Field(ge=24, le=25)
    target_frames: StrictInt = Field(ge=1, le=7500)
    segments: tuple[Segment, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def contiguous(self):
        position = 0
        for index, segment in enumerate(self.segments):
            if (
                segment.index != index
                or segment.start_frame != position
                or segment.generated_frames not in (17, 33, 49, 65, 81)
                or segment.first_frame + segment.output_frames > segment.generated_frames
            ):
                raise ValueError("Invalid or noncontiguous media timeline")
            position += segment.output_frames
        if position != self.target_frames:
            raise ValueError("Timeline does not cover the requested duration")
        return self


def timeline(*, frames, fps, seed, mode="shots", scene_frames=None, context_frames=17):
    segments = []
    position = 0
    if (
        isinstance(frames, bool)
        or not isinstance(frames, int)
        or not 1 <= frames <= 7500
        or type(fps) is not int
        or fps not in (24, 25)
        or mode not in {"continuous", "shots"}
        or isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2147483647
        or type(context_frames) is not int
        or context_frames not in (1, 17)
    ):
        raise ValueError("Invalid bounded media timing or seed")
    if scene_frames is not None and (
        mode != "shots"
        or not 1 <= len(scene_frames) <= 20
        or any(type(count) is not int or count < 1 for count in scene_frames)
        or sum(scene_frames) != frames
    ):
        raise ValueError("Invalid independent scene timing")
    boundaries = []
    boundary = 0
    for count in scene_frames or [frames]:
        boundary += count
        boundaries.append(boundary)
    while position < frames:
        first = context_frames if mode == "continuous" and segments else 0
        next_boundary = next(end for end in boundaries if end > position)
        count = min(81 - first, next_boundary - position)
        generated = next(n for n in (17, 33, 49, 65, 81) if n >= count + first)
        index = len(segments)
        derived = int.from_bytes(hashlib.sha256(f"{seed}:{index}".encode()).digest()[:4], "big") % 2147483648
        segments.append(
            Segment(
                index=index,
                start_frame=position,
                first_frame=first,
                output_frames=count,
                generated_frames=generated,
                seed=derived,
            )
        )
        position += count
    return MediaTimeline(fps=fps, target_frames=frames, segments=tuple(segments))


def duration_frames(seconds, fps=24):
    value = Fraction(str(seconds)) * fps
    if value <= 0 or value > 7500:
        raise ValueError("Unsupported media duration")
    return (value.numerator + value.denominator - 1) // value.denominator


def audio_frames(samples, rate, fps=25):
    if (
        isinstance(samples, bool)
        or not isinstance(samples, int)
        or not samples > 0
        or type(rate) is not int
        or not 8000 <= rate <= 96000
        or fps != 25
    ):
        raise ValueError("Unsupported canonical audio timing")
    return (samples * fps + rate - 1) // rate


def audio_boundary(frame, rate, fps=25):
    return frame * rate // fps
