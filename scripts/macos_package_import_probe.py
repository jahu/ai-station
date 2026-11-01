"""Native isolated interpreter/dependency acceptance, not consumer installer readiness."""

import hashlib
import io
import json
import os
import platform
import re
import sys
from pathlib import Path


def inference_requested(arguments):
    if len(arguments) not in {2, 3} or (len(arguments) == 3 and arguments[2] != "--run-native-inference"):
        raise RuntimeError("Choose the native architecture and optional explicit inference flag")
    return len(arguments) == 3


def qualify_inference(layer, result):
    """Called only after the exact isolated shipped interpreter passed its gates."""
    from macos_ci_inference import experiment, fixture

    proof = experiment(layer.parent / "inference", opted_in=True)
    frozen = fixture()
    if (
        proof.get("status") != "passed_native_probe_only"
        or proof.get("architecture") != result["architecture"]
        or proof.get("compute") != "cpu"
        or proof.get("context_size") != frozen["context_size"]
        or proof.get("model_sha256") != frozen["model"]["sha256"]
        or any(
            proof.get(key) is not True
            for key in (
                "native_inference_passed",
                "cross_process_restart_tested",
                "owner_process_exit_confirmed",
                "owned_stop_confirmed",
                "socket_cleanup_confirmed",
            )
        )
    ):
        raise ValueError("Bundled native inference and process recovery were not fully confirmed")
    result.update(
        model_inference_tested=True,
        bundled_native_inference={
            key: proof[key]
            for key in (
                "compute",
                "context_size",
                "model_sha256",
                "native_inference_passed",
                "cross_process_restart_tested",
                "owner_process_exit_confirmed",
                "owned_stop_confirmed",
                "socket_cleanup_confirmed",
            )
        },
    )


def main():
    inference = inference_requested(sys.argv)
    if (
        platform.system() != "Darwin"
        or sys.version_info[:3] != (3, 12, 14)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
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
    if inference:
        qualify_inference(layer, result)
    after = file_manifest(layer)
    after.pop("native-python.json")
    if after != actual:
        added = set(after) - set(actual)
        bytecode = sum("/__pycache__/" in name and name.endswith(".pyc") for name in added)
        print(
            json.dumps(
                {
                    "stage": "layer_inventory_changed",
                    "added_bytecode": bytecode,
                    "other_added": len(added) - bytecode,
                    "removed": len(set(actual) - set(after)),
                    "modified": sum(after[name] != actual[name] for name in set(actual) & set(after)),
                }
            ),
            flush=True,
        )
        raise ValueError("Native execution changed the shipped layer")
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
