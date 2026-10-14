"""Streaming CPU MP4 encode, canonical audio mux and full output verification."""

import hashlib
import json
import signal
import sys
import wave
from fractions import Fraction
from pathlib import Path


def source_path(root, item):
    relative = item["relative_path"]
    path = root / relative
    if (
        not relative.startswith("artifacts/")
        or path.resolve() != path
        or not path.is_file()
        or path.stat().st_size != item["size_bytes"]
    ):
        raise ValueError("Media input observation or path changed")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item["sha256"]:
        raise ValueError("Media content changed")
    return path


def checked_frames(av, root, request):
    for clip in request["clips"]:
        path = source_path(root, clip)
        count = 0
        previous = None
        with av.open(str(path)) as source:
            if len(source.streams.video) != 1:
                raise ValueError("Choose a single video stream")
            stream = source.streams.video[0]
            stream.thread_type = "SLICE"
            stream.codec_context.thread_count = 2
            if stream.codec_context.name not in {"h264", "hevc", "mpeg4", "vp9", "av1"}:
                raise ValueError("Unsupported video codec")
            for frame in source.decode(video=0):
                if count >= clip["expected_frames"]:
                    raise ValueError("Video contains excess frames")
                if frame.pts is None or frame.time_base is None:
                    raise ValueError("Missing video timing")
                timestamp = Fraction(frame.pts) * frame.time_base
                if previous is not None and timestamp <= previous:
                    raise ValueError("Nonmonotonic video timing")
                previous = timestamp
                if frame.width != request["width"] or frame.height != request["height"]:
                    raise ValueError("Segment dimensions changed")
                if clip["first_frame"] <= count < clip["first_frame"] + clip["frames"]:
                    yield frame
                count += 1
        if count != clip["expected_frames"]:
            raise ValueError("Truncated video input")


def audio_frames(av, root, item):
    path = source_path(root, item)
    with wave.open(str(path), "rb") as source:
        if (
            source.getnframes() != item["samples"]
            or source.getframerate() != item["sample_rate"]
            or source.getnchannels() not in {1, 2}
            or source.getsampwidth() not in {1, 2, 3, 4}
        ):
            raise ValueError("Canonical PCM audio observation changed")
        layout = "mono" if source.getnchannels() == 1 else "stereo"
    resampler = av.AudioResampler(format="fltp", layout=layout, rate=48000)
    count = 0
    output = 0
    with av.open(str(path)) as source:
        for frame in source.decode(audio=0):
            if frame.sample_rate != item["sample_rate"]:
                raise ValueError("Audio sample rate changed")
            count += frame.samples
            if count > item["samples"]:
                raise ValueError("Audio exceeds the canonical sample count")
            for normalized in resampler.resample(frame):
                normalized.pts = output
                normalized.time_base = Fraction(1, 48000)
                output += normalized.samples
                yield normalized
        for normalized in resampler.resample(None):
            normalized.pts = output
            normalized.time_base = Fraction(1, 48000)
            output += normalized.samples
            yield normalized
    if count != item["samples"]:
        raise ValueError("Truncated canonical audio")


def verify(av, path, request):
    print("media.stage: verifying", flush=True)
    count = 0
    previous = None
    audio_samples = 0
    with av.open(str(path)) as source:
        for frame in source.decode(video=0):
            if frame.width != request["width"] or frame.height != request["height"] or frame.pts is None:
                raise ValueError("Invalid composed frame")
            timestamp = Fraction(frame.pts) * frame.time_base
            if previous is not None and timestamp <= previous:
                raise ValueError("Invalid output timing")
            if abs(timestamp - Fraction(count, request["fps"])) > Fraction(1, request["fps"] * 100):
                raise ValueError("Output frame rate or timeline drift")
            previous = timestamp
            count += 1
    if count != request["target_frames"]:
        raise ValueError("Composed video frame count mismatch")
    if request.get("audio"):
        with av.open(str(path)) as source:
            if len(source.streams.audio) != 1:
                raise ValueError("Canonical audio track is missing")
            for frame in source.decode(audio=0):
                audio_samples += frame.samples
        expected = Fraction(request["audio"]["samples"] * 48000, request["audio"]["sample_rate"])
        if abs(audio_samples - expected) > Fraction(48000, request["fps"]):
            raise ValueError("Audio was truncated or duplicated")
    return {
        "verified": True,
        "frames": count,
        "fps": request["fps"],
        "width": request["width"],
        "height": request["height"],
        "duration_seconds": count / request["fps"],
        "audio_source_samples": request["audio"]["samples"] if request.get("audio") else None,
        "audio_source_sample_rate": request["audio"]["sample_rate"] if request.get("audio") else None,
        "decoded_audio_samples": audio_samples,
    }


def compose(config):
    import av

    request = config["request"]
    root = Path(config["root"]).resolve()
    output = Path(config["output"])
    if output.resolve() != output or not output.is_relative_to(root / "artifacts"):
        raise ValueError("Output escaped application artifacts")
    temporary = output.with_suffix(".partial.mp4")
    print("media.stage: composing", flush=True)
    video_count = 0
    audio = iter(audio_frames(av, root, request["audio"])) if request.get("audio") else iter(())
    pending = next(audio, None)
    try:
        with av.open(str(temporary), "w") as target:
            video = target.add_stream("libx264", rate=request["fps"])
            video.width = request["width"]
            video.height = request["height"]
            video.pix_fmt = "yuv420p"
            video.codec_context.thread_count = 2
            audio_stream = target.add_stream("aac", rate=48000) if request.get("audio") else None
            if audio_stream:
                audio_stream.layout = pending.layout.name if pending else "mono"
            for source in checked_frames(av, root, request):
                frame = source.reformat(format="yuv420p")
                frame.pts = video_count
                frame.time_base = Fraction(1, request["fps"])
                for packet in video.encode(frame):
                    target.mux(packet)
                video_count += 1
                while pending is not None and Fraction(pending.pts, 48000) < Fraction(
                    video_count, request["fps"]
                ):
                    for packet in audio_stream.encode(pending):
                        target.mux(packet)
                    pending = next(audio, None)
            if video_count != request["target_frames"]:
                raise ValueError("Composition did not cover the target")
            for packet in video.encode():
                target.mux(packet)
            while pending is not None:
                for packet in audio_stream.encode(pending):
                    target.mux(packet)
                pending = next(audio, None)
            if audio_stream:
                for packet in audio_stream.encode():
                    target.mux(packet)
        report = verify(av, temporary, request)
        temporary.replace(output)
        output.with_suffix(".json").write_text(json.dumps(report))
        print("media.stage: completed", flush=True)
        return report
    finally:
        close = getattr(audio, "close", None)
        if close:
            close()


if __name__ == "__main__":
    signal.alarm(1800)
    compose(json.loads(Path(sys.argv[1]).read_text()))
