"""Optional fit of complete spoken cues through elastic still-image holds."""

import math
from fractions import Fraction

from app.studio_storyboard import visual_origin


def fit_measured(storyboard, voices, sources):
    floors, weights = [], []
    for index, shot in enumerate(storyboard.scenes):
        voice = voices.get(index)
        spoken = math.ceil(Fraction(voice["samples"] * 30, voice["sample_rate"])) + 12 if voice else 30
        origin = storyboard.scenes[visual_origin(storyboard, index)]
        kind = sources.get(str(origin.source_artifact_id), {}).get("kind")
        elastic = origin.visual_kind in {"image", "graphics"} or (
            origin.visual_kind == "library" and kind == "image"
        )
        if origin.visual_kind == "library" and not elastic and spoken > shot.duration_frames:
            raise ValueError(
                f"Scene {index + 1}: complete narration needs {spoken / 30:g}s, beyond its planned Library window of {shot.duration_frames / 30:g}s. Choose a longer source window or move some narration to another scene."
            )
        floor = max(30 if elastic else shot.duration_frames, spoken)
        if floor > 2700:
            raise ValueError(f"Scene {index + 1}: complete narration exceeds the ninety-second scene limit")
        floors.append(floor)
        weights.append(max(0, shot.duration_frames - floor) if elastic else 0)
    target = max(storyboard.frames, sum(floors))
    if target > 18000:
        raise ValueError("Complete narration and retained video windows exceed the ten-minute edit limit")
    remaining = target - sum(floors)
    if remaining:
        shares = [Fraction(remaining * weight, sum(weights)) for weight in weights]
        lengths = [floor + math.floor(share) for floor, share in zip(floors, shares, strict=True)]
        for index in sorted(range(len(shares)), key=lambda i: (-(shares[i] % 1), i))[: target - sum(lengths)]:
            lengths[index] += 1
    else:
        lengths = floors
    values = storyboard.model_dump(mode="json")
    for shot, length in zip(values["scenes"], lengths, strict=True):
        shot["duration_frames"] = length
    return type(storyboard).model_validate(values)
