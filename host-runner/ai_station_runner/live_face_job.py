"""Fixed face child. Binary inference IPC never enters ordinary Run stdout logs."""

import contextlib
import json
import os
import sys
import time
from pathlib import Path

from ai_station_runner.live_ipc import bind_parent, read_sync, snapshot_bytes, write_sync
from ai_station_runner.live_protocol import Kind, Packet, StreamOrder, decode, encode


def image(data, *, reference=False):
    import cv2
    import numpy as np

    if not data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        raise ValueError("Live references must be JPEG or PNG")
    source = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError("The live image could not be decoded")
    height, width = source.shape[:2]
    if min(height, width) < 64 or height * width > (20_000_000 if reference else 1440 * 960):
        raise ValueError("The live image exceeds its admitted dimensions")
    scale = min(1.0, 960 / max(width, height))
    return cv2.resize(source, (round(width * scale), round(height * scale))) if scale < 1 else source


def serve(body, source, target):
    from ai_station_runner.live_face_engine import FaceEngine, FaceTrackingError

    bind_parent(body["parent_pid"])
    if os.environ.get("CUDA_VISIBLE_DEVICES", "").count(",") or not os.environ.get("CUDA_VISIBLE_DEVICES"):
        raise ValueError("The face child needs exactly its allocated visible GPU")
    paths = {key: Path(body[key]) for key in ("face_detector", "face_recognizer", "face_swapper")}
    engine = FaceEngine(paths["face_detector"], paths["face_recognizer"], paths["face_swapper"], gpu=0)
    engine.set_reference(
        image(snapshot_bytes(body["reference_fd"], body["reference_sha256"]), reference=True)
    )
    write_sync(target, b'J{"ready":true,"medium":"face"}')
    order = StreamOrder()
    while (raw := read_sync(source)) is not None:
        packet = decode(raw, incoming=True)
        if packet.kind != Kind.CAMERA:
            raise ValueError("The face pipe accepts only camera frames")
        order.accept(packet)
        started = time.monotonic()
        try:
            result = engine.transform(image(packet.body))
        except FaceTrackingError as exc:
            write_sync(
                target,
                b"J"
                + json.dumps({"tracking": False, "sequence": packet.sequence, "reason": str(exc)}).encode(),
            )
            continue
        ok, jpeg = engine.cv.imencode(".jpg", result, [engine.cv.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError("The transformed face could not be encoded")
        write_sync(
            target, b"P" + encode(Packet(Kind.PICTURE, packet.sequence, packet.timestamp_us, jpeg.tobytes()))
        )
        write_sync(
            target,
            b"J"
            + json.dumps(
                {
                    "tracking": True,
                    "sequence": packet.sequence,
                    "inference_ms": round((time.monotonic() - started) * 1000, 2),
                }
            ).encode(),
        )


def main():
    from ai_station_runner.environment_files import read_json

    # Must precede the first lazy OpenCV import; oversized compressed images
    # are refused by the decoder before an unbounded pixel allocation.
    os.environ["OPENCV_IO_MAX_IMAGE_PIXELS"] = "20000000"
    body = read_json(Path(sys.argv[1]))
    if set(body) != {
        "parent_pid",
        "reference_fd",
        "reference_sha256",
        "face_detector",
        "face_recognizer",
        "face_swapper",
    }:
        raise ValueError("Unknown face worker request fields")
    output = sys.stdout.buffer
    with contextlib.redirect_stdout(sys.stderr):
        serve(body, sys.stdin.buffer, output)


if __name__ == "__main__":
    main()
