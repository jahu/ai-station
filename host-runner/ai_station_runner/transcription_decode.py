"""In-memory audio decoding: no URLs, external files, video decoding or unbounded buffers."""

import io
import math

from ai_station_runner.recordings import RecordingRejected, frame_budget, recording_format


def deny_external_io(url, flags, options):
    raise PermissionError("Recordings cannot open external files or URLs")


def decode(data):
    import av
    import numpy as np

    format_name = recording_format(data)
    options = {
        "protocol_whitelist": "pipe",
        "format_whitelist": format_name,
        "enable_drefs": "0",
        "use_absolute_path": "0",
        "max_streams": "8",
        "probesize": "1048576",
        "analyzeduration": "5000000",
    }
    chunks = []
    count = 0
    decoded_seconds = 0.0
    input_end = 0.0
    output_samples = 0

    def append(samples):
        nonlocal output_samples
        output_samples += len(samples)
        if output_samples > 300 * 16000:
            raise RecordingRejected("Recording exceeds five minutes; no transcript was created")
        chunks.append(samples)

    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
    with av.open(
        io.BytesIO(data), mode="r", format=format_name, options=options, io_open=deny_external_io
    ) as container:
        if not container.streams.audio:
            raise RecordingRejected("The file has no audio stream")
        if len(container.streams) > 8:
            raise RecordingRejected("Recording has too many streams")
        stream = container.streams.audio[0]
        context = stream.codec_context
        if context.sample_rate and not 8000 <= context.sample_rate <= 96000:
            raise RecordingRejected("Unsupported recording sample rate")
        if context.layout and len(context.layout.channels) not in {0, 1, 2}:
            raise RecordingRejected("Use a mono or stereo recording")
        context.thread_count = 1
        for frame in container.decode(audio=0):
            count += 1
            if count > 100000:
                raise RecordingRejected("Recording has too many audio frames")
            if frame.samples == 0:
                continue
            decoded_seconds = frame_budget(
                frame.sample_rate, len(frame.layout.channels), frame.samples, decoded_seconds
            )
            start = float(frame.time) if frame.time is not None else input_end
            if not math.isfinite(start) or start < -1 or start > 300:
                raise RecordingRejected("Unsupported recording timestamps")
            gap = max(0.0, start - input_end)
            if start < input_end - 0.25:
                raise RecordingRejected("Recording timestamps move backwards")
            if gap > 0.02:
                if start + frame.samples / frame.sample_rate > 300.000001:
                    raise RecordingRejected("Recording exceeds five minutes")
                for output in resampler.resample(None):
                    append(output.to_ndarray().reshape(-1))
                if round(gap * 16000) > 300 * 16000 - output_samples:
                    raise RecordingRejected("Recording exceeds five minutes")
                append(np.zeros(round(gap * 16000), dtype=np.float32))
                resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
            input_end = max(input_end, start) + frame.samples / frame.sample_rate
            frame.pts = None
            for output in resampler.resample(frame):
                append(output.to_ndarray().reshape(-1))
        for output in resampler.resample(None):
            append(output.to_ndarray().reshape(-1))
    if output_samples < 1600:
        raise RecordingRejected("Recording has less than 0.1 seconds of audio")
    samples = np.concatenate(chunks)
    if not np.isfinite(samples).all():
        raise RecordingRejected("Recording contains invalid audio samples")
    np.clip(samples, -1.0, 1.0, out=samples)
    return samples, {
        "duration_seconds": output_samples / 16000,
        "sample_rate": 16000,
        "channels": 1,
        "input_format": format_name,
    }
