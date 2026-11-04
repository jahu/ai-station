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
    region_first_frame: int
    region_end_frame: int


def effects_windows(frames: int, fps: int, *, cuts: tuple[int, ...] = ()) -> list[EffectsWindow]:
    """Cover all frames without allowing a context/crossfade across a direction cut.

    Short windows hold their last frame through the model's fixed eight-second
    context; only the real interval is published. Endpoints derive from absolute
    frame positions, preventing cumulative rounding drift at 44.1kHz/24fps.
    """
    if type(fps) is not int or fps not in (24, 25):
        raise ValueError("Choose an inspected 24 or 25 FPS film")
    if type(frames) is not int or not 1 <= frames <= fps * 300:
        raise ValueError("Choose a complete film of at most five minutes")
    if (
        not isinstance(cuts, tuple)
        or len(cuts) > 32
        or any(type(cut) is not int or not 0 < cut < frames for cut in cuts)
        or tuple(sorted(set(cuts))) != cuts
    ):
        raise ValueError("Direction cuts must be ordered distinct frames inside the film")
    rate, maximum, overlap = 44100, fps * 8, fps // 4
    edges = (0, *cuts, frames)
    windows = []
    for region_start, region_end in zip(edges, edges[1:]):
        first = region_start
        previous_end_sample = 0
        while first < region_end:
            end = min(first + maximum, region_end)
            first_sample, end_sample = first * rate // fps, end * rate // fps
            windows.append(
                EffectsWindow(
                    first_frame=first,
                    frames=end - first,
                    conditioning_frames=maximum,
                    first_sample=first_sample,
                    end_sample=end_sample,
                    overlap_samples=max(0, previous_end_sample - first_sample),
                    region_first_frame=region_start,
                    region_end_frame=region_end,
                )
            )
            if end == region_end:
                break
            previous_end_sample = end_sample
            first = end - overlap
    return windows


def cue_cuts(frames: int, cues) -> tuple[int, ...]:
    """Timing only: descriptions have no authority to move these boundaries."""
    return tuple(sorted({n for cue in cues for n in (cue.start_frame, cue.end_frame) if 0 < n < frames}))


def window_prompt(first_frame: int, prompt: str, cues) -> str:
    for cue in cues:
        if cue.start_frame <= first_frame < cue.end_frame:
            return cue.prompt
    return prompt
