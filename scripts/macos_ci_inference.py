"""Explicit developer CPU inference fixture on native Mac; no consumer capability."""

import argparse
import json
import platform
import signal
import time
from pathlib import Path

from ai_station_runner import darwin_llama as native
from macos_desktop_python import fetch
from macos_inference_probe import private_directory, run

ROOT = Path(__file__).resolve().parent.parent
SAFE_FIELDS = {
    "status",
    "platform",
    "architecture",
    "os_version",
    "source_revision",
    "model_sha256",
    "compute",
    "context_size",
    "ram_mib",
    "memory_enforcement",
    "zero_swap_guaranteed",
    "macos_installer_qualified",
    "cross_process_restart_tested",
    "owner_process_exit_confirmed",
    "other_os_user_tested",
    "probe_sha256",
    "lifecycle_sha256",
    "bundle_manifest_sha256",
    "first_reply",
    "retained_reply",
    "observer_replacement",
    "native_inference_passed",
    "owned_stop_confirmed",
    "socket_cleanup_confirmed",
    "error_type",
    "stop_error_type",
    "cleanup_error_type",
    "native_failure",
}


def fixture():
    value = json.loads((ROOT / "packaging/macos/inference-fixture.json").read_text())
    item = value["model"]
    if (
        value["schema"] != 1
        or value["profile"] != "macos-native-cpu-qwen3-06b-qa-v1"
        or value["developer_fixture_only"] is not True
        or value["context_size"] != 512
        or value["source_repository"] != "Qwen/Qwen3-0.6B-GGUF"
        or value["source_revision"] != "23749fefcc72300e3a2ad315e1317431b06b590a"
        or item
        != {
            "kind": "model",
            "filename": "Qwen3-0.6B-Q8_0.gguf",
            "url": "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf",
            "sha256": "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
            "size_bytes": 639446688,
        }
    ):
        raise ValueError("The fixed native CPU inference fixture changed")
    return value


def experiment(root, *, opted_in=False):
    if not opted_in or platform.system() != "Darwin" or platform.machine() not in {"arm64", "x86_64"}:
        raise RuntimeError("Explicit native Mac CPU inference opt-in is required")
    root = Path(root)
    private_directory(root.parent)
    frozen = fixture()
    sdk = native.bundle.recipe(platform.machine())
    root.mkdir(mode=0o700)  # Never adopt another fixture/station or repeat an uncertain run.
    data = root / "data"
    data.mkdir(mode=0o700)
    deadline = time.monotonic() + 900

    def check():
        if time.monotonic() > deadline:
            raise TimeoutError("Native CPU fixture input deadline exceeded")

    fetch(data, {"inputs": [*sdk["inputs"], frozen["model"]]}, check)
    memory = native.collect(data).get("memory") or {}
    print(
        json.dumps(
            {
                "stage": "inputs_verified",
                "architecture": platform.machine(),
                "memory": {
                    key: memory.get(key)
                    for key in (
                        "available_basis",
                        "available_is_estimate",
                        "status",
                        "free_mib",
                        "inactive_mib",
                        "available_mib",
                        "total_mib",
                        "used_mib",
                    )
                },
            }
        ),
        flush=True,
    )
    try:
        result = run(
            data,
            root / "proof",
            frozen["model"]["sha256"],
            "cpu",
            frozen["context_size"],
            opted_in=True,
            cross_process=True,
        )
    except BaseException:
        proof = root / "proof/proof.json"
        if proof.is_file() and not proof.is_symlink():
            value = json.loads(proof.read_text())
            print(
                json.dumps({key: value[key] for key in SAFE_FIELDS if key in value}, sort_keys=True),
                flush=True,
            )
        raise
    safe = {key: result[key] for key in SAFE_FIELDS if key in result}
    print(json.dumps(safe, sort_keys=True), flush=True)
    return safe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-native-inference", action="store_true")
    args = parser.parse_args()

    def interrupted(*_):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        experiment(args.root, opted_in=args.run_native_inference)
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted"}))
        return 130
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
