"""Owned fixed CPU assembly; invoked only by the typed native setup coordinator."""

import json
import re
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import quote
from uuid import UUID

import httpx

from ai_station_runner.memory_scope import require_scope
from ai_station_runner.motion_image import ENTRYPOINT, inspect_image, recipe
from ai_station_runner.motion_prepare_owner import checked_daemon, create, observe, stop_and_remove
from ai_station_runner.motion_prepare_plan import BASES, fingerprint, manifest, source_archive
from ai_station_runner.runtime_install import atomic_json, client, directory, load_json
from ai_station_runner.runtime_install_job import events
from ai_station_runner.runtime_setup import validate_image

PHASES = {"bases", "sdk", "runtime", "assembling", "verifying"}


class Stopped(Exception):
    pass


def emit(phase):
    if phase not in PHASES:
        raise ValueError("Use a fixed renderer preparation phase")
    print(json.dumps({"type": "motion.prepare.progress", "phase": phase}), flush=True)


def saved_request(identity):
    saved = load_json(directory(identity) / "motion-setup.json")
    if (
        not saved
        or not saved.get("installation")
        or saved.get("request", {}).get("run_id") != identity
        or saved["request"].get("profile") != "hyperframes-cpu-linux-amd64-v1"
        or saved.get("recipe", {}).get("preparation_mode") != "owned_containers"
        or fingerprint(saved["request"]) != saved.get("request_hash")
        or fingerprint(saved["recipe"]) != saved.get("manifest_sha256")
        or saved["recipe"].get("preparation_manifest") != manifest()
        or saved["recipe"].get("renderer_recipe_sha256") != recipe()
    ):
        raise ValueError("Renderer preparation source identity changed")
    return saved


def check(identity, saved):
    current = load_json(directory(identity) / "motion-setup.json")
    if not current or current.get("request_hash") != saved["request_hash"]:
        raise ValueError("Renderer preparation ownership changed")
    if current.get("cancel_requested"):
        raise Stopped()
    if time.time() >= datetime.fromisoformat(saved["request"]["deadline_at"]).timestamp():
        raise TimeoutError("Renderer preparation deadline passed")


def image_observation(identity, saved, image_id):
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("Use the original committed renderer image identity")
    with client(saved["daemon"]["socket"]) as api:
        checked_daemon(api, saved["daemon"]["id"])
        response = api.get("/images/" + quote(image_id, safe="") + "/json")
        response.raise_for_status()
        labels = (response.json().get("Config") or {}).get("Labels") or {}
        if (
            labels.get("ai-station.motion.preparation.request") != saved["request_hash"]
            or labels.get("ai-station.motion.preparation.run") != identity
        ):
            raise ValueError("Prepared renderer image provenance changed")
    installed = inspect_image(
        image_id,
        bound={"host": "unix://" + saved["daemon"]["socket"], "daemon_id": saved["daemon"]["id"]},
    )
    # The immutable ID and existing renderer recipe are authoritative; caller
    # input never supplies an image reference or a configuration override.
    return installed


def ensure_base(api, stage, identity, saved):
    check(identity, saved)
    checked_daemon(api, saved["daemon"]["id"])
    reference = BASES[stage]
    path = "/images/" + quote(reference, safe="") + "/json"
    response = api.get(path)
    if response.status_code == 404:
        repo, digest = reference.split("@", 1)
        with api.stream(
            "POST", "/images/create", params={"fromImage": repo, "tag": digest, "platform": "linux/amd64"}
        ) as transfer:
            transfer.raise_for_status()
            for value in events(transfer):
                check(identity, saved)
                if not isinstance(value, dict) or value.get("error") or value.get("errorDetail"):
                    raise ValueError("Fixed renderer base transfer failed")
        response = api.get(path)
    response.raise_for_status()
    validate_image(response.json(), reference)


def stage(api, name, identity, saved):
    folder = directory(identity)
    check(identity, saved)
    item = create(api, folder, name, identity, saved["request_hash"], saved["daemon"]["id"])
    value, _ = observe(api, item)
    if value["State"]["Status"] != "created" or item.get("start_started"):
        raise ValueError("Inspect the original renderer preparation stage; do not replay it")
    response = api.put(
        "/containers/" + item["container_id"] + "/archive",
        params={"path": "/"},
        content=source_archive(name),
        headers={"Content-Type": "application/x-tar"},
    )
    response.raise_for_status()
    check(identity, saved)
    item["start_started"] = True
    atomic_json(folder, "motion-stage-" + name + ".json", item)
    observe(api, item)
    api.post("/containers/" + item["container_id"] + "/start").raise_for_status()
    while True:
        check(identity, saved)
        result = observe(api, item)
        if result is None:
            raise ValueError("Owned renderer preparation stage disappeared")
        state = result[0]["State"]
        if not state.get("Running"):
            if state.get("Status") != "exited" or state.get("ExitCode") != 0:
                raise ValueError("Fixed renderer component preparation failed")
            return item
        time.sleep(1)


def transfer_archive(api, source, source_path, destination, destination_path, identity, saved, limit):
    check(identity, saved)
    for item in (source, destination):
        if observe(api, item) is None:
            raise ValueError("Renderer component transfer lost its owned stage")
    folder = directory(identity)
    with tempfile.TemporaryFile(dir=folder) as archive:
        size = 0
        with api.stream(
            "GET", "/containers/" + source["container_id"] + "/archive", params={"path": source_path}
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(1024 * 1024):
                check(identity, saved)
                size += len(chunk)
                if size > limit:
                    raise ValueError("Prepared renderer component archive exceeded its bound")
                archive.write(chunk)
        archive.seek(0)

        def chunks():
            while chunk := archive.read(1024 * 1024):
                check(identity, saved)
                yield chunk

        api.put(
            "/containers/" + destination["container_id"] + "/archive",
            params={"path": destination_path},
            content=chunks(),
            headers={"Content-Type": "application/x-tar", "Content-Length": str(size)},
        ).raise_for_status()


def cleanup(identity, saved):
    with client(saved["daemon"]["socket"]) as api:
        for stage_name in reversed(tuple(BASES)):
            stop_and_remove(
                api, directory(identity), stage_name, identity, saved["request_hash"], saved["daemon"]["id"]
            )
    return True


def run(identity):
    identity = str(UUID(identity))
    require_scope(identity, 256)
    saved = saved_request(identity)
    target = saved["daemon"]
    folder = directory(identity)
    try:
        with client(target["socket"]) as api:
            emit("bases")
            for name in BASES:
                ensure_base(api, name, identity, saved)
            emit("sdk")
            sdk = stage(api, "sdk", identity, saved)
            emit("runtime")
            runtime = stage(api, "runtime", identity, saved)
            emit("assembling")
            transfer_archive(api, sdk, "/opt/sdk", runtime, "/opt", identity, saved, 512 * 1024**2)
            transfer_archive(
                api, sdk, "/usr/local/bin/node", runtime, "/usr/local/bin", identity, saved, 256 * 1024**2
            )
            check(identity, saved)
            config = {
                "User": "1000:1000",
                "WorkingDir": "/work",
                "Entrypoint": ENTRYPOINT,
                "Cmd": [],
                "Env": [
                    *runtime["base"]["Config"]["Env"],
                    "PYTHONPATH=/opt/ai-station",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "PYTHONUNBUFFERED=1",
                ],
                "Labels": {
                    "ai-station.motion.protocol": "1",
                    "ai-station.motion.recipe": recipe(),
                    "ai-station.motion.preparation.request": saved["request_hash"],
                    "ai-station.motion.preparation.run": identity,
                },
            }
            observe(api, runtime)
            # Persist intent before the one daemon commit. An uncertain reply
            # never permits a second commit or a restarted installation helper.
            atomic_json(
                folder, "motion-commit.json", {"request_hash": saved["request_hash"], "started": True}
            )
            commit_started = time.monotonic()
            remaining = datetime.fromisoformat(saved["request"]["deadline_at"]).timestamp() - time.time()
            if remaining <= 0:
                raise TimeoutError("Renderer preparation deadline passed before saving")
            response = api.post(
                "/commit",
                params={
                    "container": runtime["container_id"],
                    "pause": "true",
                    "repo": "ai-station-motion",
                    "tag": "prepared-" + identity,
                },
                json=config,
                timeout=httpx.Timeout(min(remaining, 600), connect=min(remaining, 5)),
            )
            response.raise_for_status()
            image_id = response.json()["Id"]
            emit("verifying")
            check(identity, saved)
            image_observation(identity, saved, image_id)
            atomic_json(
                folder,
                "motion-install-result.json",
                {
                    "request_hash": saved["request_hash"],
                    "image_id": image_id,
                    "commit_seconds": time.monotonic() - commit_started,
                },
            )
        return 0
    finally:
        cleanup(identity, saved)


def main():
    try:
        return run(sys.argv[1])
    except Stopped:
        return 130
    except TimeoutError:
        return 124
    except Exception as exc:
        # Registry errors can contain signed URLs. Keep native logs structural.
        print(
            json.dumps(
                {
                    "type": "motion.prepare.failed",
                    "error_type": type(exc).__name__,
                    "message": "Renderer preparation needs inspection; check storage, network and setup history",
                }
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
