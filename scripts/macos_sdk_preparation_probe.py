"""Actual installed Runner SDK preparation/Stop/restart; no model or Docker."""

import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


def stop(child):
    if child is not None:
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()  # Only the exact unreaped fixture Runner child.
            child.wait(timeout=5)


def main(architecture, *, run_native_inference=False):
    if (
        platform.system() != "Darwin"
        or platform.machine() != architecture
        or sys.version_info[:3] != (3, 12, 14)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
    ):
        raise RuntimeError("Use the actual isolated/no-bytecode native application interpreter")
    layer = Path(sys.prefix).resolve()
    root = Path(__file__).resolve().parent.parent
    module = importlib.util.find_spec("ai_station_runner")
    if (
        module is None
        or Path(module.origin).resolve()
        != layer / "lib/python3.12/site-packages/ai_station_runner/__init__.py"
    ):
        raise ValueError("SDK acceptance requires the actual installed Runner wheel")
    sys.path.insert(0, str(root / "scripts"))  # Reviewed inventory helper, never Runner source.
    from macos_application_probe import inventory, verify_layer

    _, before = verify_layer(layer, architecture, root)
    import httpx
    from ai_station_runner.darwin_llama_environment import Environment
    from ai_station_runner.source_identity import SOURCE_FINGERPRINT

    profile = f"llamacpp-native-darwin-{architecture}-b12032-v2"
    environment = Environment(profile)
    frozen = environment.recipe()
    item = frozen["inputs"][0]
    server = None
    model_proof = {}
    with tempfile.TemporaryDirectory(prefix="ais-sdk-", dir="/private/tmp") as temporary:
        work = Path(temporary).resolve()
        data, socket = work / "data", work / "uds/runner.sock"
        data.mkdir(mode=0o700)
        socket.parent.mkdir(mode=0o700)
        store = data / "models/store"
        store.mkdir(parents=True, mode=0o700)
        target = store / item["sha256"]
        size, digest = 0, hashlib.sha256()
        # One fixed public SDK dependency, not a model and not a user URL.
        with (
            httpx.stream(
                "GET",
                item["url"],
                follow_redirects=True,
                trust_env=False,
                timeout=60,
                headers={"Accept-Encoding": "identity"},
            ) as response,
            target.open("xb") as output,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes(1024 * 1024):
                size += len(chunk)
                if size > item["size_bytes"]:
                    raise ValueError("The fixed SDK dependency exceeded its bound")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o444)
        if size != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("The fixed native SDK dependency changed")
        env = {
            "PATH": os.defpath,
            "HOME": str(work),
            "AI_STATION_DATA_HOST_PATH": str(data),
            "AI_STATION_RUNNER_SOCKET": str(socket),
            "AI_STATION_CANCEL_GRACE_SECONDS": "0.1",
        }

        def launch():
            with (work / "runner.stderr").open("ab") as error:
                child = subprocess.Popen(
                    [sys.executable, "-IB", "-m", "ai_station_runner.main"],
                    cwd=work,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=error,
                )
            return child

        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket)),
            base_url="http://runner",
            timeout=15,
            trust_env=False,
        ) as client:

            def healthy(child):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError(
                            "Fixture Runner stopped: " + (work / "runner.stderr").read_text()[-3000:]
                        )
                    try:
                        response = client.get("/health")
                        if (
                            response.status_code == 200
                            and response.json().get("source_fingerprint") == SOURCE_FINGERPRINT
                        ):
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                raise TimeoutError("The installed SDK fixture Runner did not become healthy")

            def prepared(identity):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    response = client.get("/v1/setup/native-llama/" + identity)
                    response.raise_for_status()
                    result = response.json()
                    if result["status"] not in {"running", "cancel_requested"} and not (
                        result.get("process") or {}
                    ).get("completion_pending"):
                        if result["status"] != "succeeded" or not result["environment_prepared"]:
                            raise ValueError(
                                "Native SDK preparation did not complete: " + json.dumps(result)[-4000:]
                            )
                        return result
                    time.sleep(0.1)
                raise TimeoutError("Native SDK fixture preparation did not finish")

            try:
                server = launch()
                healthy(server)
                catalog = client.get("/v1/setup/native-llama", params={"profile": profile})
                catalog.raise_for_status()
                if not catalog.json()["installation_available"]:
                    raise ValueError(
                        "Native SDK prerequisites were not observed: " + json.dumps(catalog.json())
                    )
                identity = str(uuid4())
                permissions = ["manage_models", "network_read", "workspace_write"]
                selection = {"profile": profile, "permissions": permissions}
                body = {
                    **selection,
                    "run_id": identity,
                    "manifest_sha256": environment.fingerprint(frozen),
                    "deadline_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
                }
                if (
                    client.post(
                        "/v1/setup/native-llama/prepare", json={**body, "permissions": []}
                    ).status_code
                    != 403
                ):
                    raise ValueError("Missing preparation permissions were admitted")
                response = client.post("/v1/setup/native-llama/prepare", json=body)
                response.raise_for_status()
                initial = response.json()
                result = prepared(identity)
                repeated = client.post("/v1/setup/native-llama/prepare", json=body)
                repeated.raise_for_status()
                if repeated.json().get("process", {}).get("pid") != result["process"]["pid"]:
                    raise ValueError("Duplicate preparation changed its owned process")
                if (
                    client.post(
                        "/v1/setup/native-llama/prepare", json={**body, "manifest_sha256": "0" * 64}
                    ).status_code
                    != 409
                ):
                    raise ValueError("An existing SDK operation accepted another request")
                adopted = client.post(f"/v1/setup/native-llama/{identity}/adopt", json=selection)
                adopted.raise_for_status()
                shared = client.get("/v1/setup/native-llama", params={"profile": profile}).json()
                if not shared["sdk_prepared"] or identity in json.dumps(shared):
                    raise ValueError("SDK shared readiness leaked private preparation identity")
                environment.resolve_id(data, adopted.json()["environment_id"])
                canceled = str(uuid4())
                live = client.post("/v1/setup/native-llama/prepare", json={**body, "run_id": canceled})
                live.raise_for_status()
                if live.json()["alive"] is not True:
                    raise ValueError("The SDK live-Stop fixture did not observe a live owned child")
                client.post(f"/v1/setup/native-llama/{canceled}/cancel", json=selection).raise_for_status()
                stop_deadline = time.monotonic() + 15
                while True:
                    stopped = client.get("/v1/setup/native-llama/" + canceled)
                    stopped.raise_for_status()
                    stopped = stopped.json()
                    if (
                        stopped["status"] == "canceled"
                        and not stopped["alive"]
                        and not (stopped.get("process") or {}).get("completion_pending")
                    ):
                        break
                    if time.monotonic() >= stop_deadline:
                        raise TimeoutError("Live SDK Stop did not confirm process exit")
                    time.sleep(0.1)
                if client.post(f"/v1/setup/native-llama/{canceled}/adopt", json=selection).status_code != 409:
                    raise ValueError("A stopped SDK operation was activated")
                blocked = str(uuid4())
                client.post(f"/v1/setup/native-llama/{blocked}/cancel", json=selection).raise_for_status()
                fenced = client.post("/v1/setup/native-llama/prepare", json={**body, "run_id": blocked})
                fenced.raise_for_status()
                if fenced.json()["status"] != "canceled" or fenced.json().get("process"):
                    raise ValueError("Pre-dispatch Stop did not fence a delayed native launch")
                if client.post("/v1/llama/load", json={}).status_code != 422:
                    raise ValueError("Malformed model coordinates bypassed typed validation")
                if run_native_inference:
                    from macos_typed_model_probe import qualify

                    def restart():
                        nonlocal server
                        stop(server)
                        server = launch()
                        healthy(server)

                    model_proof = qualify(client, data, profile, adopted.json()["environment_id"], restart)
                stop(server)
                server = launch()
                healthy(server)
                recovered = prepared(identity)
                if recovered["process"]["pid"] != result["process"]["pid"]:
                    raise ValueError("SDK restart recovery re-executed the old operation")
                current = client.get("/v1/setup/native-llama", params={"profile": profile}).json()
                if current.get("environment") != shared["environment"]:
                    raise ValueError("SDK activation identity changed across Runner restart")
            finally:
                stop(server)
    if inventory(layer) != before:
        raise ValueError("Native SDK preparation changed the installed application interpreter")
    value = {
        "platform": "Darwin",
        "architecture": architecture,
        "os_version": platform.mac_ver()[0],
        "native_sdk_preparation_passed": True,
        "installed_Runner_main": True,
        "actual_owned_sdk_child": True,
        "duplicate_start_same_pid": True,
        "permission_denial_passed": True,
        "immutable_request_passed": True,
        "pre_dispatch_stop_passed": True,
        "actual_live_sdk_stop_passed": True,
        "stopped_sdk_activation_refused": True,
        "runner_restart_same_sdk_identity": True,
        "private_operation_not_in_shared_catalog": True,
        "application_inventory_unchanged": True,
        "model_inference_tested": bool(model_proof),
        **model_proof,
        "macos_installer_qualified": False,
        "preparation_initially_alive": initial["alive"],
    }
    print(json.dumps(value, sort_keys=True))
    return value


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--run-native-inference"):
        raise SystemExit("Choose the native architecture")
    main(sys.argv[1], run_native_inference=len(sys.argv) == 3)
