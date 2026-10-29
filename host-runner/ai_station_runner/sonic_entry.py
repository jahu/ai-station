"""Opt-in native whole-recording qualification, not a public execution API.

No adapter is advertised as operational yet. Use only a fixed internal request,
an owned kernel scope, an absolute deadline and the ordinary ProcessManager.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

from ai_station_runner.sonic_contract import (
    checked_media,
    checked_request,
    inspect_inputs,
    installation_observation,
)
from ai_station_runner.whole_avatar_timing import WholeAvatarTiming


def qualification_scope(run_id):
    from ai_station_runner.memory_scope import require_scope

    if os.environ.get("AI_STATION_REAL_GPU_TESTS") != "1":
        raise ValueError("Whole-recording qualification requires an explicit real-GPU opt-in")
    return require_scope(run_id, 18432)


def deny_network(*args, **kwargs):
    raise RuntimeError("The fixed whole-recording avatar model runs offline")


def verify_movie(path, observation):
    import av

    count, previous = 0, None
    with av.open(str(path)) as movie:
        if len(movie.streams.video) != 1 or len(movie.streams.audio) != 1:
            raise ValueError("Avatar must contain one complete video and speech stream")
        video, audio = movie.streams.video[0], movie.streams.audio[0]
        if (
            video.width != observation["width"]
            or video.height != observation["height"]
            or video.average_rate != 25
            or audio.codec_context.channels != observation["channels"]
            or audio.duration is None
            or abs(
                float(audio.duration * audio.time_base) - observation["samples"] / observation["sample_rate"]
            )
            > 1024 / observation["sample_rate"] + 0.005
        ):
            raise ValueError("Avatar output geometry or complete speech changed")
        for frame in movie.decode(video=0):
            if (
                frame.width != video.width
                or frame.height != video.height
                or frame.pts is None
                or frame.pts * frame.time_base != Fraction(count, 25)
                or (previous is not None and frame.pts <= previous)
            ):
                raise ValueError("Avatar has missing, repeated or invalid presentation timestamps")
            previous = frame.pts
            count += 1
            if count > observation["target_frames"]:
                raise ValueError("Avatar contains unexpected frames")
    if count != observation["target_frames"]:
        raise ValueError("Avatar dropped part of the complete recording")
    decoded, rate = 0, None
    with av.open(str(path)) as movie:
        for frame in movie.decode(audio=0):
            if rate is not None and frame.sample_rate != rate:
                raise ValueError("Avatar speech sample rate changed during decoding")
            rate = frame.sample_rate
            decoded += frame.samples
            if decoded > observation["samples"] * rate / observation["sample_rate"] + 1026:
                raise ValueError("Avatar duplicated canonical speech")
    if rate is None or abs(decoded - observation["samples"] * rate / observation["sample_rate"]) > 1026:
        raise ValueError("Avatar dropped canonical speech during decoding")


def run(options):
    if options.request.stat().st_size > 65536:
        raise ValueError("Oversized internal avatar request")
    request = checked_request(json.loads(options.request.read_text()))
    qualification_scope(request["run_id"])
    root, runtime, models = (
        options.data_root.resolve(),
        options.runtime_dir.resolve(),
        options.model_dir.resolve(),
    )
    if installation_observation(runtime, models) != request["recipe"]["observation"]:
        raise ValueError("Sonic implementation or model observation changed")
    observed = inspect_inputs(root, request["portrait"], request["audio"])
    if observed != request["observed_input"]:
        raise ValueError("Frozen portrait geometry or canonical PCM changed")
    from ai_station_runner.security import resolve_child

    run_id = request["run_id"]
    work = resolve_child(root, f"runs/{run_id}/whole-avatar")
    output = resolve_child(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4")
    if (
        work != root / f"runs/{run_id}/whole-avatar"
        or output != root / f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4"
        or work.exists()
        or output.exists()
    ):
        raise ValueError("Inspect existing or changed whole-recording work before retrying")
    work.mkdir(parents=True, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True)
    portrait, audio = checked_media(root, request["portrait"]), checked_media(root, request["audio"])
    from PIL import Image, ImageOps

    canvas = work / "portrait-canvas.png"
    with Image.open(portrait) as image:
        ImageOps.pad(
            ImageOps.exif_transpose(image).convert("RGB"),
            (observed["width"], observed["height"]),
            method=Image.Resampling.LANCZOS,
            color="black",
        ).save(canvas)
    os.environ.update(
        USE_TF="0", USE_FLAX="0", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1"
    )
    socket.socket.connect, socket.create_connection = deny_network, deny_network
    sys.path.insert(0, str(runtime))
    from ai_station_runner.sonic_frames import encode_recording
    from ai_station_runner.sonic_inference import generate, load_interpolator

    timing = WholeAvatarTiming(observed["samples"], observed["sample_rate"])
    frames = generate(
        runtime,
        models,
        canvas,
        audio,
        timing,
        observed["width"],
        observed["height"],
        request["seed"],
        request["device_count"],
    )
    print("avatar.finishing: interpolating the complete recording", flush=True)
    silent, partial = work / "silent.mp4", work / "complete.mp4"
    import torch

    with torch.no_grad():
        encode_recording(
            frames, timing, load_interpolator(models), silent, observed["width"], observed["height"]
        )
    del frames
    # Full canonical speech; neither -shortest nor a trimming duration may hide
    # missing frames or remove the last phoneme of a non-integral recording.
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(silent),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(partial),
        ],
        check=True,
        timeout=120,
    )
    verify_movie(partial, observed)
    checked_media(root, request["portrait"])
    checked_media(root, request["audio"])
    if installation_observation(runtime, models) != request["recipe"]["observation"]:
        raise ValueError("Sonic implementation or model observation changed during generation")
    if time.time() >= request["deadline_at"]:
        raise ValueError("Whole-recording deadline expired before publication")
    # Recheck canonical output boundaries immediately before atomic publication.
    if output != resolve_child(root, output.relative_to(root).as_posix()) or output.exists():
        raise ValueError("Avatar output boundary changed before publication")
    partial.chmod(0o600)
    partial.replace(output)
    print("avatar.completed: verified complete recording", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
