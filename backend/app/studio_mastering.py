"""Fixed streaming stereo mastering using packaged libav filters, never a shell.

A whole-file EBU meter selects one gain; a 4x oversampled limiter protects peaks.
Every pass preserves canonical PCM coverage. Quiet/gated audio is never promoted
from noise to full loudness, and reported results are measured, not target claims.
"""

import math
import wave
from fractions import Fraction
from pathlib import Path
from typing import Literal

from app.voice_level_dsp import digest

PROFILE = "studio-lufs16-v1"
MasteringProfile = Literal["studio-lufs16-v1", "none"]
RATE = 48000
BLOCK = 16384
TARGET = -16.0
MAX_GAIN_DB = 18.0
TRUE_PEAK_CEILING = -1.5
LIMITER_CEILING = 10 ** (-2.0 / 20)


def read_pcm(path, check):
    import numpy as np

    with wave.open(str(path), "rb") as source:
        if (
            source.getparams()[:3] != (2, 2, RATE)
            or source.getcomptype() != "NONE"
            or not 1 <= source.getnframes() <= 600 * RATE
        ):
            raise ValueError("Studio mastering requires canonical stereo PCM48 within ten minutes")
        total = 0
        while raw := source.readframes(BLOCK):
            check()
            if len(raw) % 4:
                raise ValueError("The canonical soundtrack is truncated")
            values = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).T.astype("float32") / 32768
            total += values.shape[1]
            if total > source.getnframes():
                raise ValueError("Soundtrack coverage changed during mastering")
            yield values
        if total != source.getnframes():
            raise ValueError("The canonical soundtrack is truncated")


def graph_nodes(kind):
    import av

    graph = av.filter.Graph()
    graph.threads = 1
    inlet = graph.add_abuffer(sample_rate=RATE, format="fltp", layout="stereo", time_base=Fraction(1, RATE))
    if kind == "meter":
        effect = graph.add("ebur128", "metadata=1:peak=true")
        inlet.link_to(effect)
    else:
        up = graph.add("aresample", "192000")
        limiter = graph.add("alimiter", f"limit={LIMITER_CEILING}:level=0:latency=1")
        effect = graph.add("aformat", "sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
        inlet.link_to(up)
        up.link_to(limiter)
        limiter.link_to(effect)
    sink = graph.add("abuffersink")
    effect.link_to(sink)
    graph.configure()
    return graph


def filtered(path, kind, check, gain=1.0):
    import av
    import numpy as np

    graph = graph_nodes(kind)
    position = 0

    def drain():
        while True:
            try:
                frame = graph.pull()
            except (av.error.BlockingIOError, av.error.EOFError):
                return
            check()
            yield frame

    for values in read_pcm(path, check):
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(values * gain), format="fltp", layout="stereo"
        )
        frame.sample_rate = RATE
        frame.time_base = Fraction(1, RATE)
        frame.pts = position
        position += frame.samples
        graph.push(frame)
        yield from drain()
    graph.push(None)
    yield from drain()


def dbfs(value):
    return 20 * math.log10(value) if value > 0 else None


def measure(path, check=lambda: None):
    import numpy as np

    samples, peak, true_peak, stats = 0, 0.0, 0.0, {}
    for frame in filtered(path, "meter", check):
        values = frame.to_ndarray()
        if not np.isfinite(values).all() or frame.sample_rate != RATE or len(frame.layout.channels) != 2:
            raise ValueError("The mastered soundtrack format changed")
        samples += frame.samples
        peak = max(peak, float(np.abs(values).max()))
        stats.update(frame.metadata)
        true_peak = max(true_peak, float(frame.metadata.get("lavfi.r128.true_peak", "0")))
    integrated = float(stats.get("lavfi.r128.I", "-70"))
    if not math.isfinite(integrated) or not math.isfinite(true_peak) or true_peak < 0:
        raise ValueError("The soundtrack loudness meter returned invalid measurements")
    # libav emits true-peak metadata rounded to three decimal places. Retain
    # that actual observation and use a conservative bound for ceiling checks.
    peak_bound = max(peak, true_peak + 0.0005) if peak else 0.0
    return {
        "samples": samples,
        "integrated_lufs": integrated if integrated > -69.9 else None,
        "true_peak_dbfs": dbfs(max(peak, true_peak)),
        "true_peak_upper_dbfs": dbfs(peak_bound),
        "sample_peak_dbfs": dbfs(peak),
        "sample_peak": peak,
    }


def master_wave(source: Path, output: Path, check=lambda: None):
    import numpy as np

    if source == output or source.is_symlink() or output.exists():
        raise ValueError("Mastering needs a new private output and a canonical source")
    identity = digest(source, check)
    before = measure(source, check)
    gain_db = (
        min(MAX_GAIN_DB, TARGET - before["integrated_lufs"]) if before["integrated_lufs"] is not None else 0.0
    )
    gain = 10 ** (gain_db / 20)
    written = 0
    if not before["sample_peak"]:
        # Preserve exact digital silence, including sub-filter-buffer lengths.
        # A lookahead limiter has nothing to protect and must not lose a tail.
        with source.open("rb") as original, output.open("xb") as target:
            while chunk := original.read(1024 * 1024):
                check()
                target.write(chunk)
        written = before["samples"]
    else:
        with output.open("xb") as raw, wave.open(raw, "wb") as target:
            target.setparams((2, 2, RATE, before["samples"], "NONE", "not compressed"))
            for frame in filtered(source, "master", check, gain):
                values = frame.to_ndarray()
                if not np.isfinite(values).all() or float(np.abs(values).max()) >= 1:
                    raise ValueError("The mastering limiter exceeded its sample ceiling")
                written += frame.samples
                if written > before["samples"]:
                    raise ValueError("Mastering added samples to the edit")
                target.writeframesraw(np.rint(values.T * 32768).astype("<i2").tobytes())
    after = measure(output, check)
    if written != before["samples"] or after["samples"] != written:
        raise ValueError("Mastering changed the soundtrack timing")
    if after["true_peak_upper_dbfs"] is not None and after["true_peak_upper_dbfs"] > TRUE_PEAK_CEILING:
        raise ValueError("The mastered soundtrack exceeded its true-peak ceiling")
    if digest(source, check) != identity:
        raise ValueError("The premaster changed during processing")
    return {
        "profile": PROFILE,
        "samples": written,
        "sample_rate": RATE,
        "channels": 2,
        "target_lufs": TARGET,
        "true_peak_ceiling_dbfs": TRUE_PEAK_CEILING,
        "maximum_gain_db": MAX_GAIN_DB,
        "gain_db": gain_db,
        "target_reached": after["integrated_lufs"] is not None
        and abs(after["integrated_lufs"] - TARGET) <= 1.0,
        "before": before,
        "after": after,
    }
