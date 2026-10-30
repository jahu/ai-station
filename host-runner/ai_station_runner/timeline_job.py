"""Fixed, bounded CPU edit/mix/export. No caller-provided filters or commands."""

import json
import os
import time
import wave
from fractions import Fraction
from pathlib import Path

from ai_station_runner.media_compose_job import source_path, verify
from ai_station_runner.memory_scope import current_group, require_scope
from ai_station_runner.security import resolve_child
from ai_station_runner.timeline_contract import RAM_MIB, TimelineRequest, duration, inspect_manifest
from ai_station_runner.timeline_observation import observation


def deadline(request):
    if time.time() >= request.deadline_at:
        raise ValueError("Timeline execution deadline elapsed")


def scan_video(av, path, source, request):
    count = 0
    with av.open(str(path)) as media:
        if len(media.streams.video) != 1:
            raise ValueError("Choose one inspected video stream")
        stream = media.streams.video[0]
        stream.codec_context.thread_count = 2
        if stream.average_rate != source.fps or stream.codec_context.name not in {
            "h264",
            "hevc",
            "mpeg4",
            "vp9",
            "av1",
        }:
            raise ValueError("Source video timing or codec changed")
        for frame in media.decode(video=0):
            if (
                frame.pts is None
                or frame.time_base is None
                or (frame.width, frame.height) != (source.width, source.height)
            ):
                raise ValueError("Source video dimensions/timing changed")
            if abs(Fraction(frame.pts) * frame.time_base - Fraction(count, source.fps)) > Fraction(
                1, source.fps * 100
            ):
                raise ValueError("Source video is not the inspected constant frame rate")
            count += 1
            if count > source.frames:
                raise ValueError("Source video has excess frames")
            if count % source.fps == 0:
                deadline(request)
    if count != source.frames:
        raise ValueError("Source video is truncated")


def decoded_audio(av, np, path, source, request):
    if source.kind == "audio":
        with wave.open(str(path)) as wav:
            if (wav.getnframes(), wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (
                source.samples,
                source.sample_rate,
                source.channels,
                source.sample_width,
            ):
                raise ValueError("Frozen WAV format changed")
    chunks, total, input_samples = [], 0, 0
    maximum = (
        (source.frames * 48000 + source.fps - 1) // source.fps + 4096
        if source.kind == "video"
        else (source.samples * 48000 + source.sample_rate - 1) // source.sample_rate + 2
    )
    with av.open(str(path)) as media:
        if not media.streams.audio and source.kind == "video":
            return np.zeros((0, 2), dtype=np.float32)
        if len(media.streams.audio) != 1:
            raise ValueError("Choose a single mono/stereo audio stream")
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        for frame in media.decode(audio=0):
            deadline(request)
            if len(frame.layout.channels) not in (1, 2) or not 8000 <= frame.sample_rate <= 96000:
                raise ValueError("Unsupported source audio format")
            if source.kind == "audio" and frame.sample_rate != source.sample_rate:
                raise ValueError("Frozen WAV rate changed")
            if (
                frame.pts is None
                or frame.time_base is None
                or abs(Fraction(frame.pts) * frame.time_base - Fraction(input_samples, frame.sample_rate))
                > Fraction(2, frame.sample_rate)
            ):
                raise ValueError("Source audio timing is not continuous from zero")
            input_samples += frame.samples
            for converted in resampler.resample(frame):
                values = converted.to_ndarray().T.copy()
                if not np.isfinite(values).all():
                    raise ValueError("Source contains non-finite audio")
                chunks.append(values)
                total += len(values)
                if total > maximum:
                    raise ValueError("Source audio exceeds the inspected duration")
        for converted in resampler.resample(None):
            values = converted.to_ndarray().T.copy()
            if not np.isfinite(values).all():
                raise ValueError("Source contains non-finite audio")
            chunks.append(values)
            total += len(values)
        if total > maximum or (source.kind == "audio" and input_samples != source.samples):
            raise ValueError("Source audio sample coverage changed")
    if not chunks:
        raise ValueError("Source audio stream is empty")
    return np.concatenate(chunks)


def mix_part(np, target, source, *, first, count, offset, end, gain, fade_in, fade_out):
    available = max(0, min(count, end - offset, len(source) - offset))
    for cursor in range(0, available, 16384):
        length = min(16384, available - cursor)
        positions = np.arange(cursor, cursor + length, dtype=np.float32)
        envelope = np.ones(length, dtype=np.float32)
        if fade_in:
            envelope *= np.minimum(1, positions / max(1, fade_in - 1))
        if fade_out:
            envelope *= np.minimum(1, (count - 1 - positions) / max(1, fade_out - 1))
        target[first + cursor : first + cursor + length] += source[
            offset + cursor : offset + cursor + length
        ] * (gain * envelope[:, None])
    return count - available


def mix_audio(av, np, request, paths, sources, frames):
    output = np.zeros((frames * 48000 // request.manifest.fps, 2), dtype=np.float32)
    groups, padded = {}, 0
    for item in [*request.manifest.clips, *request.manifest.tracks]:
        if not item.muted and item.gain:
            groups.setdefault(str(item.artifact_id), []).append(item)
    # Mix one source at a time: sixteen long clips/tracks must not retain
    # thirty-two decoded PCM buffers inside the fixed four-GiB scope.
    for identity, items in groups.items():
        deadline(request)
        source = sources[identity]
        pcm = decoded_audio(av, np, paths[identity], source, request)
        for item in items:
            deadline(request)
            if source.kind == "video":
                count = (
                    duration(item, request.manifest.fps, source.model_dump()) * 48000 // request.manifest.fps
                )
                offset, end = item.in_frame * 48000 // source.fps, item.out_frame * 48000 // source.fps
                if not len(pcm):
                    continue
            else:
                count = item.duration_frames * 48000 // request.manifest.fps
                offset = item.in_sample * 48000 // source.sample_rate
                end = len(pcm)
            padded += mix_part(
                np,
                output,
                pcm,
                first=item.start_frame * 48000 // request.manifest.fps,
                count=count,
                offset=offset,
                end=end,
                gain=item.gain,
                fade_in=item.fade_in_frames * 48000 // request.manifest.fps,
                fade_out=item.fade_out_frames * 48000 // request.manifest.fps,
            )
    if not np.isfinite(output).all():
        raise ValueError("Audio mix is not finite")
    peak = float(np.abs(output).max())
    adjustment = min(1.0, 0.98 / peak) if peak else 1.0
    output *= adjustment
    return output, {
        "unprotected_peak": peak,
        "peak_protection_gain": adjustment,
        "padded_audio_samples": padded,
    }


def clip_frames(av, np, path, source, clip, manifest):
    count = duration(clip, manifest.fps, source.model_dump())
    with av.open(str(path)) as media:
        stream = media.streams.video[0]
        stream.codec_context.thread_count = 2
        media.seek(int(Fraction(clip.in_frame, source.fps) / stream.time_base), stream=stream, backward=True)
        frames = iter(media.decode(video=0))
        frame, index = None, -1
        for output_index in range(count):
            wanted = min(clip.in_frame + output_index * source.fps // manifest.fps, clip.out_frame - 1)
            while index < wanted:
                try:
                    frame = next(frames)
                except StopIteration as exc:
                    raise ValueError("Trimmed video is incomplete") from exc
                if frame.pts is None or frame.time_base is None:
                    raise ValueError("Trimmed frame timing is missing")
                index = round(Fraction(frame.pts) * frame.time_base * source.fps)
            if index != wanted:
                raise ValueError("Trimmed video seek missed its frozen frame")
            scale = min(manifest.width / source.width, manifest.height / source.height)
            width = max(2, min(manifest.width, round(source.width * scale)))
            height = max(2, min(manifest.height, round(source.height * scale)))
            image = frame.reformat(width=width, height=height, format="rgb24").to_ndarray()
            canvas = np.zeros((manifest.height, manifest.width, 3), dtype=np.uint8)
            x, y = (manifest.width - width) // 2, (manifest.height - height) // 2
            canvas[y : y + height, x : x + width] = image
            yield av.VideoFrame.from_ndarray(canvas, format="rgb24").reformat(format="yuv420p")


def render(request, root, work, output):
    import av
    import numpy as np

    deadline(request)
    sources = {str(s.artifact_id): s for s in request.sources}
    paths = {
        identity: source_path(root, source.model_dump(mode="json")) for identity, source in sources.items()
    }
    frames = inspect_manifest(request.manifest, {k: v.model_dump(mode="json") for k, v in sources.items()})
    print("timeline.stage: inspecting", flush=True)
    for identity, source in sources.items():
        if source.kind == "video":
            scan_video(av, paths[identity], source, request)
    print("timeline.stage: mixing", flush=True)
    pcm, mix_report = mix_audio(av, np, request, paths, sources, frames)
    clips = sorted(request.manifest.clips, key=lambda c: c.start_frame)
    iterators = {
        i: iter(
            clip_frames(av, np, paths[str(c.artifact_id)], sources[str(c.artifact_id)], c, request.manifest)
        )
        for i, c in enumerate(clips)
    }
    intervals = [
        (
            c.start_frame,
            c.start_frame + duration(c, request.manifest.fps, sources[str(c.artifact_id)].model_dump()),
        )
        for c in clips
    ]
    temporary = work / "complete.partial.mp4"
    audio_cursor = 0
    try:
        with av.open(str(temporary), "w") as media:
            video = media.add_stream("libx264", rate=request.manifest.fps)
            video.width, video.height, video.pix_fmt = (
                request.manifest.width,
                request.manifest.height,
                "yuv420p",
            )
            video.codec_context.thread_count = 2
            video.options = {"preset": "veryfast", "crf": "18"}
            audio = media.add_stream("aac", rate=48000)
            audio.layout, audio.bit_rate = "stereo", 192000
            for index in range(frames):
                deadline(request)
                selected = next((i for i, (start, end) in enumerate(intervals) if start <= index < end), None)
                frame = (
                    next(iterators[selected])
                    if selected is not None
                    else av.VideoFrame.from_ndarray(
                        np.zeros((video.height, video.width, 3), dtype=np.uint8), format="rgb24"
                    ).reformat(format="yuv420p")
                )
                frame.pts, frame.time_base = index, Fraction(1, request.manifest.fps)
                for packet in video.encode(frame):
                    media.mux(packet)
                audio_end = (index + 1) * 48000 // request.manifest.fps
                while audio_cursor < audio_end:
                    end = min(audio_cursor + 2048, audio_end)
                    sample = av.AudioFrame.from_ndarray(
                        pcm[audio_cursor:end].T.copy(), format="fltp", layout="stereo"
                    )
                    sample.sample_rate, sample.pts, sample.time_base = 48000, audio_cursor, Fraction(1, 48000)
                    for packet in audio.encode(sample):
                        media.mux(packet)
                    audio_cursor = end
                if (index + 1) % request.manifest.fps == 0 or index + 1 == frames:
                    print(f"timeline.frames.completed {index + 1}/{frames}", flush=True)
            for packet in video.encode():
                media.mux(packet)
            for packet in audio.encode():
                media.mux(packet)
        print("timeline.stage: verifying", flush=True)
        report = verify(
            av,
            temporary,
            {
                "fps": request.manifest.fps,
                "width": video.width,
                "height": video.height,
                "target_frames": frames,
                "audio": {"samples": len(pcm), "sample_rate": 48000},
            },
        )
        deadline(request)
        for source in request.sources:
            source_path(root, source.model_dump(mode="json"))
        report.update(
            mix_report,
            timeline_audio_samples=len(pcm),
            timeline_audio_rate=48000,
            source_ids=sorted(sources),
            observation=request.observation,
            peak_scope_memory_bytes=int((current_group() / "memory.peak").read_text()),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.resolve() != output:
            raise ValueError("Timeline output traverses a symlink")
        report_path = output.with_suffix(".json")
        if report_path.resolve() != report_path:
            raise ValueError("Timeline report traverses a symlink")
        with report_path.open("x") as handle:
            json.dump(report, handle)
        os.link(temporary, output)
        temporary.unlink()
        print("timeline.stage: completed", flush=True)
        return report
    finally:
        for iterator in iterators.values():
            iterator.close()


def run(receipt):
    if receipt.resolve() != receipt or receipt.stat().st_size > 196608:
        raise ValueError("Invalid timeline receipt")
    record = json.loads(receipt.read_text())
    if set(record) != {"request", "python"}:
        raise ValueError("Timeline launch configuration changed")
    request = TimelineRequest.model_validate(record["request"])
    rid, root = str(request.run_id), receipt.parents[3]
    if receipt != root / f"runs/{rid}/timeline-launch/request.json":
        raise ValueError("Timeline receipt ownership changed")
    require_scope(rid, RAM_MIB)
    if observation() != request.observation:
        raise ValueError("Timeline implementation changed since queuing")
    deadline(request)
    work = resolve_child(root, f"runs/{rid}/timeline")
    output = resolve_child(root, f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4")
    if work != root / f"runs/{rid}/timeline" or work.exists() or output.exists() or output.is_symlink():
        raise ValueError("Inspect existing timeline work instead of overwriting")
    work.mkdir(mode=0o700, parents=True)
    return render(request, root, work, output)


if __name__ == "__main__":
    import sys

    run(Path(sys.argv[1]))
