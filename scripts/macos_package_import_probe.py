"""Native isolated interpreter/dependency acceptance, not consumer installer readiness."""

import hashlib
import io
import json
import os
import platform
import re
import sys
from pathlib import Path


def main():
    if (
        platform.system() != "Darwin"
        or sys.version_info[:3] != (3, 12, 14)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
        or len(sys.argv) != 2
        or sys.argv[1] not in {"arm64", "x86_64"}
        or platform.machine() != sys.argv[1]
    ):
        raise RuntimeError("Use the pinned isolated native Mac interpreter with its exact architecture")
    root = Path(__file__).resolve().parent.parent
    layer = Path(sys.executable).resolve().parent.parent
    receipt = json.loads((layer / "native-python.json").read_text())
    # Only the reviewed repository source is added; target dependencies must come
    # from the actual shipped interpreter, with user/site/PYTHONPATH disabled.
    sys.path[:0] = [str(root / "host-runner"), str(root / "scripts")]
    from macos_desktop_python import file_manifest, fingerprint, recipe

    if receipt["architecture"] != sys.argv[1] or receipt["manifest_sha256"] != fingerprint(
        recipe(sys.argv[1])
    ):
        raise ValueError("Native layer receipt differs from this reviewed source")
    actual = file_manifest(layer)
    actual.pop("native-python.json")
    if actual != receipt["files"]:
        raise ValueError("The bundled interpreter inventory changed")

    import ssl
    import venv

    import av
    import dotenv
    import fastapi
    import httptools
    import httpx
    import numpy
    import pydantic
    import uvicorn
    import uvloop
    import watchfiles
    import websockets
    from ai_station_runner.app import app
    from PIL import Image

    assert all(
        (
            ssl.OPENSSL_VERSION,
            venv.EnvBuilder,
            dotenv.load_dotenv,
            fastapi.FastAPI,
            httptools.HttpRequestParser,
            httpx.Client,
            pydantic.BaseModel,
            uvicorn.Server,
            uvloop.new_event_loop,
            watchfiles.watch,
            websockets.connect,
            app.routes,
        )
    )
    assert float(numpy.zeros(3).sum()) == 0
    assert Image.new("RGB", (1, 1)).getpixel((0, 0)) == (0, 0, 0)
    # Verify a real native FFmpeg encode/decode without a model, GPU or user asset.
    output = io.BytesIO()
    with av.open(output, "w", format="wav") as container:
        stream = container.add_stream("pcm_s16le", rate=16000)
        frame = av.AudioFrame.from_ndarray(
            numpy.zeros((1, 160), dtype=numpy.int16), format="s16", layout="mono"
        )
        frame.sample_rate = 16000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    with av.open(io.BytesIO(output.getvalue())) as container:
        assert sum(frame.samples for frame in container.decode(audio=0)) == 160
    after = file_manifest(layer)
    after.pop("native-python.json")
    if after != actual:
        raise ValueError("Native import changed the shipped layer")
    head = os.environ.get("GITHUB_SHA", "")
    result = {
        "platform": "Darwin",
        "os_version": platform.mac_ver()[0],
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "source_head": head if re.fullmatch(r"[a-f0-9]{40}", head) else None,
        "layer_manifest_sha256": receipt["manifest_sha256"],
        "layer_receipt_sha256": hashlib.sha256((layer / "native-python.json").read_bytes()).hexdigest(),
        "native_dependency_imports_passed": True,
        "synthetic_audio_roundtrip_passed": True,
        "source_Runner_import_passed": True,
        "layer_inventory_unchanged": True,
        "model_inference_tested": False,
        "DockerDesktop_transport_tested": False,
        "Metal_inference_tested": False,
        "macos_installer_qualified": False,
    }
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
