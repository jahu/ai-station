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


def fit_timing(plan, duration_seconds, *, limits=None):
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
    if limits:
        return bounded_fit(plan, target, limits)
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


def bounded_fit(plan, target, limits):
    """Water-fill elastic beat weights without extending an inspected clip."""
    caps = [min(2700, limits.get(i, 2700)) for i in range(len(plan.scenes))]
    if any(type(cap) is not int or cap < 30 for cap in caps):
        raise ValueError("A selected clip window cannot cover the minimum one-second scene")
    if sum(caps) < target:
        raise ValueError(
            "Available clip windows cannot cover the requested duration; add elastic stills/graphics or plan longer new footage"
        )
    if plan.frames == target and all(
        s.duration_frames <= cap for s, cap in zip(plan.scenes, caps, strict=True)
    ):
        return plan
    remaining = target - 30 * len(caps)
    frames = [30] * len(caps)
    free = list(range(len(caps)))
    while free:
        weight = sum(plan.scenes[i].duration_frames for i in free)
        shares = {i: Fraction(remaining * plan.scenes[i].duration_frames, weight) for i in free}
        saturated = [i for i in free if shares[i] >= caps[i] - 30]
        if saturated:
            for i in saturated:
                frames[i] = caps[i]
                remaining -= caps[i] - 30
            free = [i for i in free if i not in saturated]
            continue
        for i in free:
            frames[i] += math.floor(shares[i])
        left = remaining - sum(math.floor(v) for v in shares.values())
        for i in sorted(free, key=lambda i: (-(shares[i] % 1), i))[:left]:
            frames[i] += 1
        break
    value = plan.model_dump(mode="json")
    for shot, length in zip(value["scenes"], frames, strict=True):
        shot["duration_frames"] = length
    return type(plan).model_validate(value)


def fit_source_timing(plan, duration_seconds, catalog):
    """Inspected Library windows are finite; stills can absorb the edit's timing.

    Avoid lengthening planned generated-video beats when elastic stills exist.
    These descriptive bounds do not replace native source/hash inspection.
    """
    origins = [plan.scenes[visual_origin(plan, i)] for i in range(len(plan.scenes))]
    elastic = any(
        s.visual_kind in {"image", "graphics"}
        or (s.visual_kind == "library" and catalog.get(str(s.source_artifact_id), {}).get("kind") == "image")
        for s in origins
    )
    limits = {}
    for i, (shot, origin) in enumerate(zip(plan.scenes, origins, strict=True)):
        source = catalog.get(str(origin.source_artifact_id), {})
        if elastic and (
            origin.visual_kind == "video" or origin.visual_kind == "library" and source.get("kind") == "video"
        ):
            limits[i] = shot.duration_frames
        duration = source.get("duration_seconds")
        if (
            origin.visual_kind == "library"
            and type(duration) in (int, float)
            and math.isfinite(duration)
            and duration > 0
        ):
            available = math.floor((duration - shot.media_start_seconds) * 30 + 1e-8)
            limits[i] = min(limits.get(i, 2700), available)
    return fit_timing(plan, duration_seconds, limits=limits)
