"""Bounded media observations shared by the isolated motion renderer tests."""

import json
import subprocess


def probe(installed, path):
    result = subprocess.run(
        [
            installed["ffprobe"],
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames,sample_rate,channels:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    if len(result.stdout) > 128000:
        raise ValueError("Media inspection exceeded its bound")
    return json.loads(result.stdout)


def check_source(installed, source, path, request):
    if source.kind == "image":
        from PIL import Image

        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 4096**2:
                raise ValueError("Use inspected PNG, JPEG or WebP images within the image profile")
            image.verify()
        return
    info = probe(installed, path)
    kind = "video" if source.kind == "video" else "audio"
    streams = [s for s in info["streams"] if s.get("codec_type") == kind]
    if len(streams) != 1:
        raise ValueError("Choose one complete inspected video or audio stream")
    seconds = float(info.get("format", {}).get("duration", 0))
    if not 0 < seconds <= 601:
        raise ValueError("Source duration exceeds the motion profile")
    if kind == "video":
        stream = streams[0]
        if not 1 <= stream.get("width", 0) * stream.get("height", 0) <= 4096**2:
            raise ValueError("Video dimensions exceed the motion profile")
        presenter = request.composition.presenter
        if (
            presenter
            and presenter.media == source.artifact_id
            and presenter.media_start_seconds + request.composition.frames / 30 > seconds + 1 / 30
        ):
            raise ValueError("The presenter clip must cover the entire film without looping or freezing")
        for scene in request.composition.scenes:
            if (
                scene.media == source.artifact_id
                and scene.media_start_seconds + scene.duration_frames / 30 > seconds + 1 / 30
            ):
                raise ValueError(
                    "Planned shot exceeds the actual source video; revise timing or generate a longer shot"
                )
    else:
        if (
            streams[0].get("codec_name") != "pcm_s16le"
            or streams[0].get("sample_rate") != "48000"
            or streams[0].get("channels") != 2
        ):
            raise ValueError("Use the canonical 48-kHz stereo PCM soundtrack")
        if abs(seconds - request.composition.frames / 30) > 1 / 48000:
            raise ValueError("Final audio must cover the complete material without cutting speech")
