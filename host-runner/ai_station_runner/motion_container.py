"""Fixed image entry point. It accepts only the owned mounted render request."""

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from ai_station_runner.motion_assets import asset_names, container_limits, request_digest, stage_assets
from ai_station_runner.motion_codec import check_source, probe
from ai_station_runner.motion_contract import MotionRequest
from ai_station_runner.motion_document import document


def main():
    bounds = container_limits()
    raw = Path("/work/request.json")
    if raw.is_symlink() or not raw.is_file() or raw.stat().st_size > 512000:
        raise ValueError("Expected a bounded fixed render request")
    request = MotionRequest.model_validate_json(raw.read_bytes())
    if str(request.run_id) != os.environ.get("AI_STATION_RUN_ID") or request_digest(
        request
    ) != os.environ.get("AI_STATION_MOTION_REQUEST"):
        raise ValueError("Motion container request binding changed")
    root = Path("/work/project")
    names = asset_names(request)
    installed = {"ffprobe": "/usr/bin/ffprobe", "ffmpeg": "/usr/bin/ffmpeg"}
    for source in request.sources:
        target = root / names[str(source.artifact_id)]
        if target.is_symlink() or target.resolve() != target:
            raise ValueError("Motion source traverses a symlink")
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size != source.size_bytes
                or hashlib.file_digest(handle, "sha256").hexdigest() != source.sha256
            ):
                raise ValueError("Motion source bytes changed")
        check_source(installed, source, target, request)
    stage_assets("/opt/sdk", root)
    html, compilation = document(request.composition, names, audio=request.audio_artifact_id is not None)
    (root / "index.html").write_text(html)
    output = Path("/work/output")
    output.mkdir(mode=0o700)
    report_path = output / "layout.json"
    env = {
        **os.environ,
        "HOME": "/tmp/home",
        "XDG_CACHE_HOME": "/tmp/cache",
        "HYPERFRAMES_BROWSER_PATH": "/usr/bin/chromium",
        "HYPERFRAMES_FFMPEG_PATH": "/usr/bin/ffmpeg",
        "HYPERFRAMES_FFPROBE_PATH": "/usr/bin/ffprobe",
        "HYPERFRAMES_NO_UPDATE_CHECK": "1",
        "CI": "1",
        "DO_NOT_TRACK": "1",
        "HYPERFRAMES_NO_TELEMETRY": "1",
        "TMPDIR": "/work/tmp",
        "CUDA_VISIBLE_DEVICES": "",
        "NVIDIA_VISIBLE_DEVICES": "none",
    }
    Path(env["HOME"]).mkdir(mode=0o700)
    Path(env["TMPDIR"]).mkdir(mode=0o700)
    subprocess.run(
        [
            "/usr/local/bin/node",
            str(Path(__file__).with_name("motion_qc.mjs")),
            str(root),
            "/opt/sdk",
            "/usr/bin/chromium",
            str(report_path),
        ],
        env=env,
        check=True,
        timeout=120,
    )
    qc = json.loads(report_path.read_text())
    if qc.get("verified") is not True:
        raise ValueError("Motion layout inspection failed")
    print("motion.layout.verified", flush=True)
    temporary = output / "render.mp4"
    subprocess.run(
        [
            "/usr/local/bin/node",
            "/opt/sdk/node_modules/hyperframes/bin/hyperframes.mjs",
            "render",
            str(root),
            "--output",
            str(temporary),
            "--fps",
            "30",
            "--quality",
            "high",
            "--workers",
            "2",
            "--no-browser-gpu",
            "--strict",
            "--frames-cache-dir",
            "off",
        ],
        env=env,
        check=True,
        timeout=3300,
    )
    info = probe(installed, temporary)
    video = [s for s in info["streams"] if s.get("codec_type") == "video"]
    sound = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    if (
        len(video) != 1
        or video[0].get("codec_name") != "h264"
        or video[0].get("avg_frame_rate") != "30/1"
        or (video[0]["width"], video[0]["height"]) != (request.composition.width, request.composition.height)
        or int(video[0].get("nb_read_frames", 0)) != request.composition.frames
    ):
        raise ValueError("Encoded video dimensions, frames or timing changed")
    if bool(sound) != bool(request.audio_artifact_id) or len(sound) > 1:
        raise ValueError("The encoded audio differs from the requested soundtrack")
    if abs(float(info["format"]["duration"]) - request.composition.frames / 30) > 1 / 30:
        raise ValueError("Encoded duration differs from the storyboard")
    subprocess.run(
        [
            "/usr/bin/ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(temporary),
            "-f",
            "null",
            "-",
        ],
        env=env,
        check=True,
        timeout=600,
    )
    report = {
        "verified": True,
        "run_id": str(request.run_id),
        "request_sha256": request_digest(request),
        "observation": request.observation,
        "engine": "Hyperframes 0.9.26",
        "width": request.composition.width,
        "height": request.composition.height,
        "fps": 30,
        "frames": request.composition.frames,
        "duration_seconds": request.composition.frames / 30,
        "has_audio": bool(sound),
        "compilation": compilation,
        "layout": qc["layout"],
        "bounds": bounds,
    }
    (output / "report.json").write_text(json.dumps(report))
    print("motion.export.verified", flush=True)


if __name__ == "__main__":
    main()
