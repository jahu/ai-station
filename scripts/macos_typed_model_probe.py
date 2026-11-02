"""Explicit fixed CPU fixture through the installed Runner's normal typed API."""

import hashlib
import json
import platform
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def qualify(client, data, profile, environment_id, restart):
    if platform.system() != "Darwin":
        raise RuntimeError("Typed native inference requires an actual Mac")
    from ai_station_runner.darwin_llama import memory_budget
    from ai_station_runner.gguf_context import inspect_context
    from macos_ci_inference import fixture
    from macos_desktop_python import fetch

    frozen = fixture()
    deadline = time.monotonic() + 420

    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError("Typed CPU model qualification exceeded its deadline")

    fetch(data, {"inputs": [frozen["model"]]}, check)
    model = data / "models/store" / frozen["model"]["sha256"]
    info = model.stat()
    geometry = inspect_context(model, info.st_size, info.st_mtime)
    identity = str(uuid4())
    body = {
        "instance_id": identity,
        "run_id": str(uuid4()),
        "runtime_profile": profile,
        "environment_id": environment_id,
        "app_owned": True,
        "model_path": "models/store/" + frozen["model"]["sha256"],
        "model_sha256": frozen["model"]["sha256"],
        "size_bytes": info.st_size,
        "mtime": info.st_mtime,
        "gpus": [],
        "context_size": frozen["context_size"],
        "cache_type": "q8_0",
        "ram_mib": memory_budget(info.st_size, frozen["context_size"], geometry),
        "startup_deadline_at": (datetime.now(UTC) + timedelta(minutes=3)).isoformat(),
        "permissions": ["manage_models", "filesystem_read"],
    }

    def observed(target, wanted):
        while True:
            check()
            response = client.get("/v1/llama/" + target)
            response.raise_for_status()
            value = response.json()
            if value["status"] == wanted:
                return value
            if value["status"] not in {"loading", "stopping"}:
                raise ValueError("Typed native model requires inspection: " + json.dumps(value))
            time.sleep(0.1)

    def reply():
        text, done, size = [], False, 0
        request = {
            "model": identity,
            "messages": [{"role": "user", "content": "Reply with the text MAC_TYPED_OK."}],
            "temperature": 0,
            "max_tokens": 128,
            "stream": True,
            "reasoning": {"enabled": False},
        }
        with client.stream("POST", f"/v1/llama/{identity}/chat/completions", json=request) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                check()
                size += len(line.encode())
                if size > 262144:
                    raise ValueError("Typed native stream exceeded its bound")
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    done = True
                    continue
                value = json.loads(value)
                if done or value.get("error"):
                    raise ValueError("Typed native stream failed")
                for choice in value.get("choices", []):
                    part = choice.get("delta", {}).get("content")
                    if part is not None:
                        if not isinstance(part, str):
                            raise ValueError("Typed text completion was not text")
                        text.append(part)
        content = "".join(text).strip()
        if not done or not content:
            raise ValueError("Typed model produced no complete answer")
        return {"characters": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest()}

    selection = {"permissions": ["manage_models"]}
    try:
        denied = client.post("/v1/llama/load", json={**body, "permissions": []})
        if denied.status_code != 403:
            raise ValueError("Typed load accepted missing permissions")
        client.post("/v1/llama/load", json=body).raise_for_status()
        first = observed(identity, "ready")
        if first.get("n_ctx") != frozen["context_size"] or first.get("compute_target") != "cpu":
            raise ValueError("Typed runtime context/CPU target changed")
        duplicate = client.post("/v1/llama/load", json=body)
        duplicate.raise_for_status()
        if duplicate.json().get("pid") != first["pid"]:
            raise ValueError("Repeated load created another model process")
        if client.post("/v1/llama/load", json={**body, "context_size": 1024}).status_code != 409:
            raise ValueError("Typed model request was mutable")
        initial_reply = reply()
        restart()
        retained = observed(identity, "ready")
        if retained.get("pid") != first["pid"]:
            raise ValueError("Runner restart re-executed the native model")
        retained_reply = reply()
        client.post(f"/v1/llama/{identity}/stop", json=selection).raise_for_status()
        if observed(identity, "stopped")["alive"]:
            raise ValueError("Typed Stop did not confirm process exit")
        delayed = str(uuid4())
        client.post(f"/v1/llama/{delayed}/stop", json=selection).raise_for_status()
        response = client.post(
            "/v1/llama/load", json={**body, "instance_id": delayed, "run_id": str(uuid4())}
        )
        response.raise_for_status()
        if response.json()["status"] != "stopped" or response.json().get("alive"):
            raise ValueError("Stop did not fence the delayed native load")
        return {
            "typed_native_CPU_inference_passed": True,
            "typed_duplicate_same_PID": True,
            "typed_restart_same_PID_and_reply": True,
            "typed_live_Stop_confirmed": True,
            "typed_pre_dispatch_Stop_confirmed": True,
            "model_sha256": frozen["model"]["sha256"],
            "context_size": frozen["context_size"],
            "first_reply": initial_reply,
            "retained_reply": retained_reply,
            "Metal_inference_tested": False,
            "DockerDesktop_transport_tested": False,
            "macos_installer_qualified": False,
        }
    finally:
        client.post(f"/v1/llama/{identity}/stop", json=selection).raise_for_status()
        observed(identity, "stopped")
