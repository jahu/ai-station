"""Frame-exact conditioning windows for a reusable synchronized effects stem."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EffectsWindow:
    first_frame: int
    frames: int
    conditioning_frames: int
    first_sample: int
    end_sample: int
    overlap_samples: int


def effects_windows(frames: int, fps: int) -> list[EffectsWindow]:
    """Cover the inspected film with <=8s windows, retaining its entire tail.

    Consecutive windows share about 250ms of the same source timeline for a
    later equal-time crossfade. Short windows hold their last frame through the
    model's fixed eight-second context; only the real interval is published. PCM
    endpoints always derive from absolute frame positions, preventing cumulative
    rounding drift at 44.1kHz/24fps.
    """
    if type(fps) is not int or fps not in (24, 25):
        raise ValueError("Choose an inspected 24 or 25 FPS film")
    if type(frames) is not int or not 1 <= frames <= fps * 300:
        raise ValueError("Choose a complete film of at most five minutes")
    rate = 44100
    maximum = fps * 8
    overlap = fps // 4
    windows = []
    first = 0
    previous_end_sample = 0
    while first < frames:
        end = min(first + maximum, frames)
        first_sample, end_sample = first * rate // fps, end * rate // fps
        windows.append(
            EffectsWindow(
                first_frame=first,
                frames=end - first,
                conditioning_frames=maximum,
                first_sample=first_sample,
                end_sample=end_sample,
                overlap_samples=max(0, previous_end_sample - first_sample),
            )
        )
        if end == frames:
            break
        previous_end_sample = end_sample
        first = end - overlap
    return windows
