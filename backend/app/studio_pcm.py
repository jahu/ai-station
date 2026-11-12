"""Streaming PCM edit: preserve complete narration, duck the score, export exact frames."""

import math
import wave
from contextlib import ExitStack
from fractions import Fraction

RATE = 48000
SAMPLES_PER_FRAME = 1600
CUE = 9600  # 200 ms of breathing room before/after the complete spoken cue.
BLOCK = 16384


def timed_storyboard(storyboard, voices, *, policy=None, sources=None):
    if policy == "fit":
        from app.studio_measured_timing import fit_measured

        return fit_measured(storyboard, voices, sources or {})
    values = storyboard.model_dump(mode="json")
    for index, source in voices.items():
        speech_frames = math.ceil(Fraction(source["samples"] * 30, source["sample_rate"]))
        values["scenes"][index]["duration_frames"] = max(
            values["scenes"][index]["duration_frames"], speech_frames + 12
        )
    return type(storyboard).model_validate(values)


class Reader:
    """One owned PCM file, one bounded decoder/resampler buffer; no source-sized arrays."""

    def __init__(self, stack, handle, source, check):
        import av

        self.source, self.check = source, check
        self.media = stack.enter_context(av.open(handle, "r", format="wav"))
        if len(self.media.streams.audio) != 1:
            raise ValueError("Use one PCM audio stream")
        self.stream = self.media.streams.audio[0]
        self.stream.codec_context.thread_count = 1
        self.resampler = av.AudioResampler(format="fltp", layout="stereo", rate=RATE)
        self.blocks = self.converted()
        self.pending = None
        self.offset = 0

    def converted(self):
        import numpy as np

        decoded, total = 0, 0
        maximum = math.ceil(Fraction(self.source["samples"] * RATE, self.source["sample_rate"])) + 2
        for frame in self.media.decode(self.stream):
            self.check()
            if (
                frame.sample_rate != self.source["sample_rate"]
                or len(frame.layout.channels) != self.source["channels"]
            ):
                raise ValueError("Frozen PCM format changed")
            decoded += frame.samples
            if decoded > self.source["samples"]:
                raise ValueError("Audio exceeds the observed sample coverage")
            for converted in self.resampler.resample(frame):
                values = converted.to_ndarray().T
                if not np.isfinite(values).all():
                    raise ValueError("Audio contains non-finite samples")
                total += len(values)
                if total > maximum:
                    raise ValueError("Resampled audio exceeds its frozen duration")
                yield values
        for converted in self.resampler.resample(None):
            total += converted.samples
            if total > maximum:
                raise ValueError("Resampler tail exceeds its duration")
            values = converted.to_ndarray().T
            if not np.isfinite(values).all():
                raise ValueError("Resampler tail contains non-finite samples")
            yield values
        if decoded != self.source["samples"] or not total:
            raise ValueError("PCM source is empty or truncated")

    def read(self, count):
        import numpy as np

        target = np.zeros((count, 2), dtype=np.float32)
        copied = 0
        while copied < count:
            if self.pending is None or self.offset == len(self.pending):
                self.pending = next(self.blocks, None)
                self.offset = 0
                if self.pending is None:
                    break
            available = min(count - copied, len(self.pending) - self.offset)
            target[copied : copied + available] = self.pending[self.offset : self.offset + available]
            copied += available
            self.offset += available
        return target, copied

    def complete(self):
        # Advancing to EOF validates the final decoded count, never discards a word.
        _, excess = self.read(1)
        if excess:
            raise ValueError("The edit would cut the end of a spoken cue")


def mix(
    storyboard,
    voices,
    music,
    open_source,
    temporary,
    output,
    *,
    music_gain=0.22,
    duck=0.28,
    check=lambda: None,
):
    """Two streaming passes provide one global peak limit without pumping or clipping.

    Only the instrumental score may be trimmed/faded to the edit. Narration must
    reach its actual EOF. Temporary float PCM stays on app-owned disk, not RAM.
    """
    import numpy as np

    total = storyboard.frames * SAMPLES_PER_FRAME
    peak = 0.0
    with ExitStack() as stack, temporary.open("xb") as bus:
        bed = Reader(stack, open_source(stack, music), music, check) if music else None
        position = 0
        for index, scene in enumerate(storyboard.scenes):
            frames = scene.duration_frames * SAMPLES_PER_FRAME
            source = voices.get(index)
            # Close each cue as soon as its scene ends; sixty shots do not retain
            # sixty native demuxers, file descriptors or decode buffers.
            with ExitStack() as cue_stack:
                cue = Reader(cue_stack, open_source(cue_stack, source), source, check) if source else None
                source_samples = (
                    math.ceil(Fraction(source["samples"] * RATE, source["sample_rate"])) if source else 0
                )
                for local in range(0, frames, BLOCK):
                    check()
                    count = min(BLOCK, frames - local)
                    signal = np.zeros((count, 2), dtype=np.float32)
                    speech_first, speech_end = max(local, CUE), min(local + count, CUE + source_samples)
                    if cue and speech_end > speech_first:
                        values, copied = cue.read(speech_end - speech_first)
                        if copied < speech_end - speech_first - 2:
                            raise ValueError("Narration is shorter than its observed duration")
                        signal[speech_first - local : speech_end - local] += values
                    if bed:
                        values, copied = bed.read(count)
                        if copied != count:
                            raise ValueError(
                                "Music does not cover the complete edit; generate a longer score"
                            )
                        absolute = np.arange(position + local, position + local + count, dtype=np.float64)
                        fade = np.minimum(1.0, (total - 1 - absolute) / RATE)
                        fade *= np.minimum(1.0, absolute / (RATE * 0.35))
                        if source:
                            # Smooth 120-ms attack/release around the spoken cue;
                            # no per-syllable music pumping.
                            times = np.arange(local, local + count, dtype=np.float64)
                            before = np.clip((CUE - times) / (RATE * 0.12), 0.0, 1.0)
                            after = np.clip((times - CUE - source_samples) / (RATE * 0.12), 0.0, 1.0)
                            fade *= duck + (1.0 - duck) * np.maximum(before, after)
                        signal += values * (music_gain * fade[:, None])
                    if not np.isfinite(signal).all():
                        raise ValueError("The soundtrack bus is not finite")
                    peak = max(peak, float(np.abs(signal).max()))
                    bus.write(signal.astype("<f4").tobytes())
                if cue:
                    cue.complete()
            position += frames
        if position != total:
            raise ValueError("The soundtrack does not cover its complete timeline")
    adjustment = min(1.0, 0.95 / peak) if peak else 1.0
    with temporary.open("rb") as bus, output.open("xb") as target, wave.open(target, "wb") as writer:
        writer.setparams((2, 2, RATE, total, "NONE", "not compressed"))
        written = 0
        while raw := bus.read(BLOCK * 2 * 4):
            check()
            values = np.frombuffer(raw, dtype="<f4")
            if len(values) % 2:
                raise ValueError("Temporary soundtrack data changed")
            writer.writeframesraw(np.rint(values * (32767 * adjustment)).astype("<i2").tobytes())
            written += len(values) // 2
        if written != total:
            raise ValueError("Soundtrack sample coverage changed")
    return {
        "samples": total,
        "duration_seconds": storyboard.frames / 30,
        "sample_rate": RATE,
        "channels": 2,
        "peak_before": peak,
        "peak_after": peak * adjustment,
        "global_gain": adjustment,
        "music_gain": music_gain,
        "duck": duck,
        "profile": "studio-pcm48-v1",
    }
