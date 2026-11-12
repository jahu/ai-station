"""Exact, contiguous speech parts for the fixed single-recording avatar profile."""

import wave

from app.studio_pcm import BLOCK, RATE, SAMPLES_PER_FRAME

MAX_FRAMES = 60 * 30
MIN_SAMPLES = 21 * SAMPLES_PER_FRAME  # 0.7 s, above Sonic's 0.68-s minimum.


def intervals(plan):
    boundaries, end = [], 0
    for scene in plan.scenes:
        end += scene.duration_frames
        boundaries.append(end)
    start, parts = 0, []
    while start < plan.frames:
        limit = min(start + MAX_FRAMES, plan.frames)
        end = (
            max((b for b in boundaries if start + MAX_FRAMES // 2 <= b <= limit), default=limit)
            if limit < plan.frames
            else limit
        )
        parts.append({"start_frame": start, "duration_frames": end - start})
        start = end
    if len(parts) > 32:
        raise ValueError("Narration exceeds the bounded presenter timeline")
    return parts


def split(stem, plan, directory, *, check=lambda: None):
    """No re-encoding, speech trimming, overlap or timeline drift between parts."""
    parts = []
    with wave.open(str(stem), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) != (
            RATE,
            2,
            2,
            plan.frames * SAMPLES_PER_FRAME,
        ):
            raise ValueError("The narration stem must cover the exact saved edit")
        for index, interval in enumerate(intervals(plan)):
            check()
            count = interval["duration_frames"] * SAMPLES_PER_FRAME
            padded = max(count, MIN_SAMPLES)
            path = directory / f"narration-{index + 1:02}.wav"
            with path.open("xb") as handle, wave.open(handle, "wb") as target:
                target.setparams((2, 2, RATE, padded, "NONE", "not compressed"))
                left = count
                while left:
                    check()
                    wanted = min(BLOCK, left)
                    raw = source.readframes(wanted)
                    if len(raw) != wanted * 4:
                        raise ValueError("The complete narration stem is truncated")
                    target.writeframesraw(raw)
                    left -= wanted
                target.writeframesraw(b"\0" * ((padded - count) * 4))
            parts.append({**interval, "samples": padded, "padding_samples": padded - count, "path": path})
        if source.tell() != source.getnframes():
            raise ValueError("Narration parts did not retain all samples")
    return parts
