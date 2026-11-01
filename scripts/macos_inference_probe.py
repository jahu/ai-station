"""Opt-in actual native model experiment; never installer/platform qualification."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import stat
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from ai_station_runner import darwin_llama as native
from ai_station_runner.local_model import Completion
from ai_station_runner.runtime_install import atomic_json
from ai_station_runner.speech_environment import verified_object


def private_directory(path):
    path = Path(path)
    info = path.lstat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Use a canonical private directory owned by the current user")
    return path


async def reply(manager, identity):
    class Incoming:
        async def is_disconnected(self):
            return False

    request = Completion(
        model=str(identity),
        messages=[{"role": "user", "content": "Reply with the text MAC_NATIVE_OK."}],
        temperature=0,
        max_tokens=128,
        stream=True,
        reasoning={"enabled": False},
    )

    async def receive():
        response = await manager.completion(identity, request, Incoming())
        data = bytearray()
        try:
            async for chunk in response.body_iterator:
                data.extend(chunk.encode() if isinstance(chunk, str) else chunk)
                if len(data) > 262144:
                    raise ValueError("Native probe response exceeds its bound")
        finally:
            await response.body_iterator.aclose()
        return data

    data = await asyncio.wait_for(receive(), timeout=120)
    text = []
    done = False
    for line in data.decode("utf-8").splitlines():
        if not line.startswith("data:"):
            continue
        item = line[5:].strip()
        if item == "[DONE]":
            done = True
            continue
        value = json.loads(item)
        if done or not isinstance(value, dict) or value.get("error"):
            raise ValueError("Native probe stream failed")
        for choice in value.get("choices", []):
            part = choice.get("delta", {}).get("content")
            if part is not None:
                if not isinstance(part, str):
                    raise ValueError("Native probe content must be text")
                text.append(part)
    content = "".join(text).strip()
    if not done or not content:
        raise ValueError("Native probe did not receive a complete text response")
    return {"characters": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest()}


def run(data_root, output, digest, compute, context_size, *, opted_in=False):
    architecture = platform.machine()
    version = platform.mac_ver()[0]
    if (
        not opted_in
        or platform.system() != "Darwin"
        or os.geteuid() == 0
        or architecture not in {"arm64", "x86_64"}
        or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version)
        or tuple(map(int, version.split("."))) < (13, 3)
    ):
        raise RuntimeError("Explicit opt-in on an ordinary native macOS 13.3+ user is required")
    if compute not in {"cpu", "metal"} or (compute == "metal" and architecture != "arm64"):
        raise ValueError("Select CPU or the reviewed Apple Silicon Metal profile")
    root = private_directory(data_root)
    output = Path(output)
    private_directory(output.parent)
    # A developer fixture must not adopt a running/previous station or its journal.
    if os.path.lexists(root / "runtime"):
        raise ValueError("Use fresh probe data containing verified inputs but no runtime directory")
    deadline = time.monotonic() + 900

    def check():
        if time.monotonic() > deadline:
            raise TimeoutError("Native probe preparation/startup deadline exceeded")

    model = native.verify_owned_model(root, "models/store/" + digest, digest)
    info = model.stat()
    verified_object(root, {"sha256": digest, "size_bytes": info.st_size}, check)
    context = native.inspect_context(model, info.st_size, info.st_mtime)
    ram = native.memory_budget(info.st_size, context_size, context)
    device = None
    if compute == "metal":
        report = native.collect(root).get("metal") or {}
        devices = report.get("devices") or []
        if not report.get("complete") or len(devices) != 1:
            raise ValueError("Native Metal probe needs one completely observed device")
        device = devices[0].get("registry_id")
    output.mkdir(mode=0o700)  # Existing proof is never overwritten/replayed.
    proof = {
        "status": "preparing",
        "platform": "Darwin",
        "architecture": architecture,
        "os_version": version,
        "source_revision": native.bundle.SOURCE,
        "model_sha256": digest,
        "compute": compute,
        "context_size": context_size,
        "ram_mib": ram,
        "memory_enforcement": "admission_only",
        "zero_swap_guaranteed": False,
        "macos_installer_qualified": False,
        "cross_process_restart_tested": False,
        "other_os_user_tested": False,
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "lifecycle_sha256": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
    }
    atomic_json(output, "proof.json", proof)
    managers = []
    body = None
    sockets = None
    stopped = False
    try:
        (root / "runtime").mkdir(mode=0o700)  # Exclusive claim, including concurrent probe invocations.
        operation = uuid4()
        prepared = native.bundle.prepare(
            root, operation, architecture, check=check, progress=lambda _: check()
        )
        proof["bundle_manifest_sha256"] = prepared["manifest_sha256"]
        # /tmp is an alias on macOS; resolve the directory we just created,
        # rather than attempting a long per-user temporary socket address.
        sockets = Path(tempfile.mkdtemp(prefix="ais-mac-", dir="/tmp")).resolve(strict=True)
        manager = native.NativeLlamaManager(root, sockets)
        managers.append(manager)
        body = native.NativeLoad(
            instance_id=uuid4(),
            run_id=uuid4(),
            bundle_operation_id=operation,
            bundle_manifest_sha256=prepared["manifest_sha256"],
            architecture=architecture,
            compute=compute,
            metal_registry_id=device,
            model_path="models/store/" + digest,
            model_sha256=digest,
            size_bytes=info.st_size,
            mtime=info.st_mtime,
            context_size=context_size,
            ram_mib=ram,
            startup_deadline_at=datetime.now(timezone.utc) + timedelta(seconds=600),
            permissions=["manage_models", "filesystem_read"],
        )
        proof.update(
            status="loading",
            instance_id=str(body.instance_id),
            run_id=str(body.run_id),
            socket_root=str(sockets),
        )
        atomic_json(output, "proof.json", proof)
        manager.load(body)
        while True:
            check()
            snapshot = manager.inspect(body.instance_id)
            if snapshot["status"] == "ready":
                break
            if snapshot["status"] != "loading":
                raise RuntimeError("Native probe requires inspection before continuation")
            time.sleep(0.1)
        proof["first_reply"] = asyncio.run(reply(manager, body.instance_id))
        pid = snapshot["pid"]
        manager.close()
        replacement = native.NativeLlamaManager(root, sockets)
        managers.append(replacement)
        attached = replacement.load(body)
        if attached["status"] != "ready" or attached["pid"] != pid:
            raise ValueError("Native observer replacement did not retain the original ready model")
        proof["retained_reply"] = asyncio.run(reply(replacement, body.instance_id))
        proof.update(observer_replacement=True, native_inference_passed=True)
    except BaseException as exc:
        proof.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        try:
            if managers and body is not None:
                snapshot = managers[-1].stop(body.instance_id, ["manage_models"])
                stop_deadline = time.monotonic() + 3
                while snapshot["status"] == "stopping" and time.monotonic() < stop_deadline:
                    time.sleep(0.05)
                    snapshot = managers[-1].inspect(body.instance_id)
                stopped = snapshot["status"] in {"stopped", "failed"} and snapshot["alive"] is False
                if not stopped:
                    proof.update(status="inspection_required")
            elif body is None:
                stopped = True  # No dispatch was possible yet.
        except BaseException as exc:
            proof.update(status="inspection_required", stop_error_type=type(exc).__name__)
            raise
        finally:
            for manager in managers:
                manager.close()
            proof["owned_stop_confirmed"] = stopped
            if stopped and sockets is not None:
                try:
                    shutil.rmtree(sockets)
                    proof["socket_cleanup_confirmed"] = True
                except OSError as exc:
                    proof.update(
                        status="inspection_required",
                        cleanup_error_type=type(exc).__name__,
                        socket_cleanup_confirmed=False,
                    )
            if proof.get("native_inference_passed") and stopped and proof["status"] == "loading":
                proof["status"] = "passed_native_probe_only"
            atomic_json(output, "proof.json", proof)
    if not stopped or proof["status"] != "passed_native_probe_only":
        raise RuntimeError("Inspect the retained native process and proof before continuing")
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--compute", choices=["cpu", "metal"], required=True)
    parser.add_argument("--context-size", type=int, default=4096)
    parser.add_argument("--run-native-inference", action="store_true")
    args = parser.parse_args()

    def interrupted(*_):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        result = run(
            args.data_root,
            args.output,
            args.model_sha256,
            args.compute,
            args.context_size,
            opted_in=args.run_native_inference,
        )
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted"}))
        return 130
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps({"status": result["status"], "macos_installer_qualified": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
