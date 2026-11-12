"""Native preparation lifecycle over fixed owned CPU stages and one shared image."""

import sys
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import HTTPException

from ai_station_runner import motion_install_job as job
from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import scope_environment, scope_prefix
from ai_station_runner.motion_prepare_owner import checked_daemon
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.runtime_install import atomic_json, base, client, daemon, directory, load_json
from ai_station_runner.windows_storage import disk_usage

RAM_MIB = 2304
MINIMUM_FREE_BYTES = 8 * 1024**3
EXECUTOR = "motion_environment_setup"


def manager():
    from ai_station_runner.app import manager as process_manager

    return process_manager()


def prerequisites():
    target = daemon()
    if disk_usage(target["data_root"]).free < MINIMUM_FREE_BYTES:
        raise ValueError("Free at least 8 GiB in Docker storage to prepare film export")
    if disk_usage(get_settings().host_data_dir()).free < 2 * 1024**3:
        raise ValueError("Free at least 2 GiB in application storage to prepare film export")
    return target


def active():
    from ai_station_runner import motion_setup as setup

    saved = load_json(base() / "motion-active.json")
    if saved:
        identity = str(UUID(saved["run_id"]))
        previous = setup.record(identity)
        if previous is None:
            raise HTTPException(409, "The previous renderer preparation needs inspection")
        result = snapshot(identity, previous)
        if result["alive"] or result["requires_inspection"]:
            raise HTTPException(409, "Another renderer preparation is active or needs inspection")


def start(body, frozen):
    from ai_station_runner import motion_setup as setup

    identity = str(body.run_id)
    target = prerequisites()
    value = body.model_dump(mode="json")
    saved = {
        "request": value,
        "request_hash": setup.fingerprint(value),
        "manifest_sha256": body.manifest_sha256,
        "recipe": frozen,
        "installation": True,
        "dispatch_started": True,
        "cancel_requested": False,
        "daemon": target,
        "selection_before": setup.fingerprint(load_json(setup.selection_path() / "selection.json")),
    }
    setup.save(identity, saved)
    atomic_json(base(), "motion-active.json", {"run_id": identity})
    root = get_settings().host_data_dir().resolve()
    try:
        manager().start(
            run_id=identity,
            argv=[
                *scope_prefix(identity, 256),
                sys.executable,
                "-m",
                "ai_station_runner.motion_install_job",
                identity,
            ],
            cwd=root,
            executor=EXECUTOR,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                "AI_STATION_DATA_HOST_PATH": str(root),
                "AI_STATION_DATA_DIR": str(root),
                **scope_environment(),
            },
            deadline_at=body.deadline_at.timestamp(),
        )
    except (OSError, ValueError):
        # Dispatch intent is already durable. Return its authoritative
        # observation rather than turn a lost launch reply into a rejection.
        pass
    return snapshot(identity, saved)


def committed(identity, saved):
    folder = directory(identity)
    result = load_json(folder / "motion-install-result.json")
    if result:
        if result.get("request_hash") != saved["request_hash"]:
            raise ValueError("Prepared renderer result identity changed")
        return result["image_id"]
    intent = load_json(folder / "motion-commit.json")
    if not intent:
        return None
    if intent.get("request_hash") != saved["request_hash"]:
        raise ValueError("Renderer commit identity changed")
    with client(saved["daemon"]["socket"]) as api:
        import json

        checked_daemon(api, saved["daemon"]["id"])
        response = api.get(
            "/images/json",
            params={
                "filters": json.dumps(
                    {
                        "label": [
                            "ai-station.motion.preparation.request=" + saved["request_hash"],
                            "ai-station.motion.preparation.run=" + identity,
                        ]
                    }
                )
            },
        )
        response.raise_for_status()
        values = response.json()
        if not isinstance(values, list) or len(values) != 1:
            raise ValueError("The original renderer image commit needs inspection; do not repeat it")
        image_id = values[0]["Id"]
    job.image_observation(identity, saved, image_id)
    atomic_json(
        folder, "motion-install-result.json", {"request_hash": saved["request_hash"], "image_id": image_id}
    )
    return image_id


def snapshot(identity, saved, *, stdout_offset=0, stderr_offset=0):
    from ai_station_runner import motion_setup as setup

    result = {
        "run_id": str(identity),
        "runner_id": get_settings().runner_id,
        "status": "interrupted",
        "alive": False,
        "requires_inspection": False,
        "process": None,
        "manifest_sha256": saved.get("manifest_sha256"),
        "image": None,
    }
    try:
        process = manager().inspect(str(identity), stdout_offset=stdout_offset, stderr_offset=stderr_offset)
        if process.get("executor") != EXECUTOR:
            raise ValueError("Renderer preparation process ownership changed")
        result.update(process=process, alive=bool(process.get("alive") or process.get("completion_pending")))
        if result["alive"]:
            result["status"] = "cancel_requested" if saved.get("cancel_requested") else "running"
            return result
        # A dead helper is not proof that its Docker stages are gone. Inspect
        # and remove only its frozen exact containers before releasing RAM.
        image_id = committed(str(identity), saved)
        job.cleanup(str(identity), saved)
        if saved.get("cancel_requested"):
            result["status"] = "canceled"
            return result
        if image_id:
            installed = job.image_observation(str(identity), saved, image_id)
            if saved.get("recipe") != setup.recipe() or get_settings().motion_image:
                raise ValueError("Renderer setup changed before activation")
            path = setup.selection_path() / "selection.json"
            selected = load_json(path)
            selection = {
                "protocol": 1,
                "recipe_sha256": installed["recipe_sha256"],
                "image_id": installed["image_id"],
                "activation_request_hash": saved["request_hash"],
            }
            if selected != selection:
                if (
                    saved.get("selection_published")
                    or setup.fingerprint(selected) != saved["selection_before"]
                ):
                    raise ValueError("Renderer selection changed during preparation")
                atomic_json(path.parent, path.name, selection)
            observed = setup.observation(installed)
            saved.update(selection_published=True)
            setup.save(identity, saved)
            result.update(
                status="succeeded", image=setup.descriptor(installed), renderer_observation=observed
            )
        elif process.get("exit_code") is not None:
            result["status"] = "failed"
    except (ProcessNotOwned, OSError, ValueError, KeyError, TypeError, HTTPException, httpx.HTTPError):
        result["requires_inspection"] = True
    return result


def cancel(identity, saved):
    from ai_station_runner import motion_setup as setup

    saved["cancel_requested"] = True
    setup.save(identity, saved)
    try:
        process = manager().inspect(str(identity))
        if process.get("executor") != EXECUTOR:
            raise HTTPException(409, "Renderer preparation process ownership changed")
        manager().cancel(str(identity))
    except ProcessNotOwned:
        pass
    return snapshot(identity, saved)
