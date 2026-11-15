"""Fixed portrait child, sharing the existing bounded face IPC and parent binding."""

import contextlib
import os
import sys
from pathlib import Path

from ai_station_runner.environment_files import read_json
from ai_station_runner.live_face_job import serve


def engine(body):
    from ai_station_runner.live_portrait_engine import PortraitEngine

    return PortraitEngine(
        Path(body["face_detector"]),
        {k: Path(v) for k, v in body["portrait_models"].items()},
        Path(body["portrait_sdk"]),
        gpu=0,
    )


def main():
    os.environ["OPENCV_IO_MAX_IMAGE_PIXELS"] = "20000000"
    body = read_json(Path(sys.argv[1]))
    if set(body) != {
        "parent_pid",
        "reference_fd",
        "reference_sha256",
        "face_detector",
        "portrait_sdk",
        "portrait_models",
    }:
        raise ValueError("Unknown portrait worker request fields")
    output = sys.stdout.buffer
    with contextlib.redirect_stdout(sys.stderr):
        serve(body, sys.stdin.buffer, output, engine_factory=engine)


if __name__ == "__main__":
    main()
