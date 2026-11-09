"""Fixed CPU speech leveling; no models, subprocesses or caller-supplied filters."""

import hashlib
import math
from fractions import Fraction
from pathlib import Path

PROFILE = "speech-volume-v1"
MAX_SECONDS = 300
FILTER = "f=250:g=5:p=0.84:m=6:r=0.12:t=0.01:c=1"


def digest(path, check=lambda: None):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            check()
            value.update(block)
    return value.hexdigest()


class Meter:
    def __init__(self, rate):
        self.rate = rate
        self.peak = 0.0
        self.levels = []
        self.square_sum = 0.0
        self.count = 0
        self.block_sum = 0.0
        self.block_samples = 0
        self.block_values = 0

    def add(self, frame):
        import numpy as np

        values = frame.to_ndarray()
        if values.ndim != 2 or values.shape[1] != frame.samples or not np.isfinite(values).all():
            raise ValueError("Audio contains invalid samples")
        self.peak = max(self.peak, float(np.max(np.abs(values))))
        self.square_sum += float(np.sum(values.astype("float64") ** 2))
        self.count += values.size
        offset = 0
        while offset < frame.samples:
            count = min(self.rate - self.block_samples, frame.samples - offset)
            part = values[:, offset : offset + count].astype("float64")
            self.block_sum += float(np.sum(part**2))
            self.block_values += part.size
            self.block_samples += count
            offset += count
            if self.block_samples == self.rate:
                self.flush()

    def flush(self):
        rms = math.sqrt(self.block_sum / max(1, self.block_values))
        if rms >= 0.01:
            self.levels.append(20 * math.log10(rms))
        self.block_sum = 0.0
        self.block_values = 0
        self.block_samples = 0

    def report(self):
        import numpy as np

        return {
            "peak_dbfs": round(20 * math.log10(max(self.peak, 1e-12)), 3),
            "rms_dbfs": round(10 * math.log10(max(self.square_sum / max(1, self.count), 1e-24)), 3),
            "active_range_db": round(
                float(np.percentile(self.levels, 90) - np.percentile(self.levels, 10)), 3
            )
            if self.levels
            else 0.0,
        }


def level_wave(source: Path, output: Path, check=lambda: None):
    """Decode only owned WAV/MP4 audio and keep its exact decoded sample count."""
    import av

    frames_in = frames_out = 0
    offset = None
    if output.exists() or source == output:
        raise ValueError("Choose a new speech output")
    with (
        source.open("rb") as raw,
        av.open(
            raw,
            format="wav" if source.suffix == ".wav" else "mov",
            options={"enable_drefs": "0", "use_absolute_path": "0"},
        ) as src,
    ):
        if len(src.streams.audio) != 1:
            raise ValueError("Choose a recording with one audio track")
        stream = src.streams.audio[0]
        rate = stream.codec_context.sample_rate
        channels = stream.codec_context.channels
        if channels not in (1, 2) or not 8000 <= rate <= 96000:
            raise ValueError("Use mono/stereo audio at 8000–96000 Hz")
        before, after = Meter(rate), Meter(rate)
        layout = "mono" if channels == 1 else "stereo"
        convert = av.AudioResampler(format="fltp", layout=layout, rate=rate)
        graph = av.filter.Graph()
        inlet = graph.add_abuffer(sample_rate=rate, format="fltp", layout=layout, time_base=Fraction(1, rate))
        compressor = graph.add(
            "acompressor", "threshold=0.0625:ratio=3:attack=10:release=250:knee=2.828:makeup=1:detection=rms"
        )
        dynamic = graph.add("dynaudnorm", FILTER)
        limiter = graph.add("alimiter", "limit=0.89125:level=0:latency=1")
        fmt = graph.add("aformat", f"sample_fmts=fltp:sample_rates={rate}:channel_layouts={layout}")
        sink = graph.add("abuffersink")
        inlet.link_to(compressor)
        compressor.link_to(dynamic)
        dynamic.link_to(limiter)
        limiter.link_to(fmt)
        fmt.link_to(sink)
        graph.configure()
        with (
            output.open("xb") as target_file,
            av.open(target_file, "w", format="wav", options={"fflags": "+bitexact"}) as target,
        ):
            encoder = target.add_stream("pcm_s16le", rate=rate)
            encoder.layout = layout

            def drain():
                nonlocal frames_out
                while True:
                    try:
                        frame = graph.pull()
                    except (av.error.BlockingIOError, av.error.EOFError):
                        break
                    check()
                    after.add(frame)
                    frame.pts = frames_out
                    frame.time_base = Fraction(1, rate)
                    frames_out += frame.samples
                    for packet in encoder.encode(frame):
                        target.mux(packet)

            for decoded in src.decode(stream):
                check()
                if offset is None:
                    offset = float(decoded.pts * decoded.time_base) if decoded.pts is not None else 0.0
                for frame in convert.resample(decoded):
                    frames_in += frame.samples
                    if frames_in > rate * MAX_SECONDS:
                        raise ValueError("Voice leveling supports recordings up to five minutes")
                    before.add(frame)
                    frame.pts = frames_in - frame.samples
                    frame.time_base = Fraction(1, rate)
                    graph.push(frame)
                    drain()
            for frame in convert.resample(None):
                frames_in += frame.samples
                before.add(frame)
                graph.push(frame)
                drain()
            graph.push(None)
            drain()
            for packet in encoder.encode():
                target.mux(packet)
        if frames_in != frames_out or not frames_out or after.peak > 0.999:
            raise ValueError("Speech leveling changed timing or exceeded its peak ceiling")
    return {
        "profile": PROFILE,
        "sample_rate": rate,
        "channels": channels,
        "samples": frames_out,
        "audio_start_seconds": offset or 0.0,
        "before": before.report(),
        "after": after.report(),
        "method": "soft_knee_compression_smoothed_rms_gain_and_peak_limiter",
        "max_gain_db": round(20 * math.log10(6), 3),
    }


def mux_voice(source, wave_path, output, report, check=lambda: None):
    """Copy encoded video packets; replace only the audio track, retaining offset."""
    import av

    def packets(container, stream):
        for packet in container.demux(stream):
            if packet.dts is not None:
                yield packet

    def timing(packet):
        return repr(
            tuple(None if v is None else Fraction(v) * packet.time_base for v in (packet.pts, packet.dts))
        ).encode()

    with (
        source.open("rb") as raw,
        av.open(raw, format="mov", options={"enable_drefs": "0"}) as src,
        av.open(str(wave_path), format="wav") as audio,
        output.open("xb") as raw_out,
        av.open(raw_out, "w", format="mp4", options={"movflags": "+faststart"}) as dst,
    ):
        if len(src.streams.video) != 1:
            raise ValueError("Choose a video with one picture stream")
        original = src.streams.video[0]
        video = dst.add_stream_from_template(original)
        video.metadata.update(original.metadata)
        sound = dst.add_stream("aac", rate=report["sample_rate"])
        sound.layout = "mono" if report["channels"] == 1 else "stereo"
        sound.bit_rate = 192000

        def sound_packets():
            samples = round(report["audio_start_seconds"] * report["sample_rate"])
            for frame in audio.decode(audio=0):
                check()
                frame.pts = samples
                frame.time_base = Fraction(1, report["sample_rate"])
                samples += frame.samples
                yield from sound.encode(frame)
            yield from sound.encode()

        movies, sounds = iter(packets(src, original)), iter(sound_packets())
        v, a = next(movies, None), next(sounds, None)
        video_hash = hashlib.sha256()
        timing_hash = hashlib.sha256()
        count = 0
        while v is not None or a is not None:
            check()
            if v is not None and (a is None or v.dts * v.time_base <= a.dts * a.time_base):
                video_hash.update(bytes(v))
                timing_hash.update(timing(v))
                count += 1
                v.stream = video
                dst.mux(v)
                v = next(movies, None)
            else:
                dst.mux(a)
                a = next(sounds, None)
    with av.open(str(output), format="mov") as completed:
        copied = hashlib.sha256()
        copied_timing = hashlib.sha256()
        copied_count = 0
        for packet in packets(completed, completed.streams.video[0]):
            check()
            copied.update(bytes(packet))
            copied_timing.update(timing(packet))
            copied_count += 1
        if (
            copied.digest() != video_hash.digest()
            or count != copied_count
            or copied_timing.digest() != timing_hash.digest()
        ):
            raise ValueError("Video packets changed during voice processing")
        sound = completed.streams.audio[0]
        offset = float(sound.start_time * sound.time_base) if sound.start_time is not None else 0.0
        duration = float(sound.duration * sound.time_base) if sound.duration is not None else None
        if (
            abs(offset - report["audio_start_seconds"]) > 2 / report["sample_rate"]
            or duration is None
            or abs(duration - report["samples"] / report["sample_rate"]) > 2 / report["sample_rate"]
        ):
            raise ValueError("Processed audio timing differs from the source")
    report.update(
        video_reencoded=False, video_packets_sha256=video_hash.hexdigest(), video_timestamps_preserved=True
    )
    return report
