"""Owned native child: a single pinned image pull over a local Docker Unix API.

Closing the one streaming request cancels Docker's daemon-side pull. No arbitrary
Docker method, image reference or socket is accepted from HTTP/CLI callers.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from uuid import UUID

from ai_station_runner import runtime_setup
from ai_station_runner.runtime_install import atomic_json, client, directory, inspect_image, read


def emit(kind, **value):
    print(json.dumps({"type": kind, **value}), flush=True)


def events(response):
    pending = b""
    for chunk in response.iter_bytes():
        pending += chunk
        if len(pending) > 128 * 1024:
            raise ValueError("Docker progress exceeded its bound")
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if line.strip():
                yield json.loads(line)
    if pending.strip():
        yield json.loads(pending)


def run(identity):
    identity = str(UUID(identity))
    saved = read(identity)
    if saved is None or saved.get("cancel_requested"):
        return 130
    request = saved["request"]
    selection = runtime_setup.RuntimeSelection(profile=request["profile"])
    frozen = runtime_setup.recipe(selection)
    if (
        request["run_id"] != identity
        or runtime_setup.fingerprint(request) != saved["request_hash"]
        or frozen != saved["recipe"]
        or runtime_setup.fingerprint(frozen) != saved["manifest_sha256"]
    ):
        raise ValueError("Runtime preparation source identity changed")
    remaining = datetime.fromisoformat(request["deadline_at"]).timestamp() - time.time()
    if not 0 < remaining <= 4 * 3600:
        return 124
    timer = threading.Timer(remaining, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        target = saved["daemon"]
        with client(target["socket"]) as api:
            info = api.get("/info")
            info.raise_for_status()
            if info.json().get("ID") != target["id"]:
                raise ValueError("The local Docker daemon changed")
            repo, digest = frozen["image_reference"].split("@", 1)
            emit("runtime.prepare.started", expected_bytes=frozen["download_bytes"])
            received = {}
            with api.stream(
                "POST",
                "/v" + target["api_version"] + "/images/create",
                params={"fromImage": repo, "tag": digest, "platform": frozen["platform"]},
            ) as response:
                response.raise_for_status()
                for value in events(response):
                    if not isinstance(value, dict):
                        raise ValueError("Docker returned an invalid progress event")
                    if value.get("error") or value.get("errorDetail"):
                        raise ValueError("The pinned runtime registry transfer failed")
                    layer = str(value.get("id", "")).removeprefix("sha256:")
                    matches = [key for key in frozen["layers"] if len(layer) >= 12 and key.startswith(layer)]
                    status = str(value.get("status", ""))[:160]
                    if len(matches) == 1:
                        key = matches[0]
                        current = (value.get("progressDetail") or {}).get("current")
                        if status in {"Already exists", "Download complete", "Pull complete"}:
                            received[key] = frozen["layers"][key]
                        elif type(current) is int and current >= 0 and status == "Downloading":
                            received[key] = min(current, frozen["layers"][key])
                    emit(
                        "runtime.prepare.progress",
                        stage="unpacking" if status.startswith("Extract") else "downloading",
                        received_bytes=sum(received.values()),
                        expected_bytes=frozen["download_bytes"],
                        message=status,
                    )
            emit("runtime.prepare.verifying")
            image = inspect_image(api, frozen)
            if image is None:
                raise ValueError("The prepared runtime image could not be verified")
        if read(identity).get("cancel_requested"):
            return 130
        atomic_json(
            directory(identity), "result.json", {"request_hash": saved["request_hash"], "image": image}
        )
        emit("runtime.prepare.verified", image_id=image["id"])
        return 0
    finally:
        timer.cancel()


def main():
    try:
        return run(sys.argv[1])
    except Exception:
        # Public registry errors can contain signed redirect/auth URLs. Preserve
        # structured outcome without copying those URLs or local config to logs.
        emit(
            "runtime.prepare.failed",
            message="Pinned runtime preparation failed; inspect source, storage and network availability",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
