"""Whole-recording timing and bounded portrait geometry; no inference dependencies.

The configured model Python also imports this module, so keep it Python 3.10
compatible. Nothing in this module advertises an available executor.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WholeAvatarTiming:
    samples: int
    sample_rate: int

    def __post_init__(self):
        if (
            type(self.samples) is not int
            or type(self.sample_rate) is not int
            or not 8000 <= self.sample_rate <= 96000
            or self.samples * 100 < self.sample_rate * 68
            or self.samples > self.sample_rate * 60
        ):
            raise ValueError("Use an intact PCM recording of 0.68–60 seconds")

    @property
    def target_frames(self):
        return (self.samples * 25 + self.sample_rate - 1) // self.sample_rate

    @property
    def base_frames(self):
        return (self.target_frames + 1) // 2

    @property
    def feature_frames(self):
        # Upstream floors the audio length before taking every second frame.
        # Its Whisper features already contain padding; retain the real tail
        # by requesting the rounded-up base length rather than flooring speech.
        return self.base_frames * 2

    @property
    def endpoint_frames(self):
        # RIFE interpolates between N base images, yielding 2*N-1 frames.
        # An even target needs exactly one final 40-ms presentation hold.
        return self.target_frames - (self.base_frames * 2 - 1)


def portrait_canvas(width, height, *, max_side):
    """Return a canvas bounded by the explicitly frozen resolution profile.

    Fit/pad the source into this canvas before calling upstream preprocessing,
    which otherwise scales the *shortest* side and can exceed the GPU budget.
    """
    if type(max_side) is not int or max_side not in {384, 768}:
        raise ValueError("Choose an explicit bounded 384- or 768-pixel profile")
    if (
        type(width) is not int
        or type(height) is not int
        or not 32 <= min(width, height) <= max(width, height) <= 8192
        or max(width, height) > min(width, height) * 4
    ):
        raise ValueError("Choose a bounded portrait with aspect ratio at most 4:1")
    longest = max(width, height)

    def aligned(side):
        return ((side * max_side + longest * 64 - 1) // (longest * 64)) * 64

    return aligned(width), aligned(height)


def whole_portrait_canvas(width, height):
    """Fit every allowed source aspect inside the frozen pixel budget.

    Keep the measured 512×768 portrait unchanged. Other aspect ratios use a
    smaller aligned canvas when needed, with uniform fit/pad during preprocessing.
    A square source must not accidentally allocate a 768×768 attention window.
    """
    portrait_canvas(width, height, max_side=768)  # Validate source bounds first.
    longest = max(width, height)
    for bound in range(768, 191, -64):
        canvas = tuple(((side * bound + longest * 64 - 1) // (longest * 64)) * 64 for side in (width, height))
        if canvas[0] * canvas[1] <= 512 * 768:
            return canvas
    raise ValueError("Portrait does not fit the bounded whole-recording canvas")
