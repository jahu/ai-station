"""Pure editorial compilation: explicit shared sources and deterministic 30fps timing."""

import math
from fractions import Fraction


def visual_origin(plan, index):
    """Validated references always go backward; no model-selected paths or IDs."""
    if not 0 <= index < len(plan.scenes):
        raise ValueError("Choose a scene in this storyboard")
    for _ in range(len(plan.scenes)):
        shot = plan.scenes[index]
        if shot.visual_kind != "reuse":
            return index
        if shot.reuse_scene is None or not 0 <= shot.reuse_scene < index:
            raise ValueError("A shared visual must resolve to an earlier source")
        index = shot.reuse_scene
    raise ValueError("Shared visual references cannot form a cycle")


def source_end_seconds(plan, index):
    """One generated clip must cover the trim window of every referencing scene."""
    origin = visual_origin(plan, index)
    return max(
        s.duration_frames / 30 + s.media_start_seconds
        for i, s in enumerate(plan.scenes)
        if visual_origin(plan, i) == origin
    )


def fit_timing(plan, duration_seconds):
    """Fit directed beat weights without discarding content or trusting LLM arithmetic.

    Only the director calls this. Manual saved edits and measured spoken timing
    retain their own explicit authority. Largest remainders give exact frames.
    """
    target = duration_seconds * 30
    count = len(plan.scenes)
    if target < count * 30:
        raise ValueError("Use fewer scenes or a longer duration: every scene needs at least one second")
    if target > count * 2700:
        raise ValueError("Split this longer material into more scenes of at most ninety seconds")
    if plan.frames == target:
        return plan
    remaining = target - count * 30
    weights = [s.duration_frames for s in plan.scenes]
    allocations = [Fraction(remaining * weight, sum(weights)) for weight in weights]
    frames = [30 + math.floor(value) for value in allocations]
    leftovers = target - sum(frames)
    order = sorted(range(count), key=lambda i: (-(allocations[i] % 1), i))
    for i in order[:leftovers]:
        frames[i] += 1
    if any(n > 2700 for n in frames):
        raise ValueError(
            "Redistribute the planned beats or add scenes: each scene must stay within ninety seconds"
        )
    value = plan.model_dump(mode="json")
    for shot, length in zip(value["scenes"], frames, strict=True):
        shot["duration_frames"] = length
    return type(plan).model_validate(value)
