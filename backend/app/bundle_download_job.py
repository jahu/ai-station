"""Verify every companion object before publishing a shared model-file bundle."""

import asyncio
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.model_bundles import Bundle
from app.model_download_files import DownloadBusy, directory, obtain
from app.model_download_job import DownloadExecutor, LostClaim, Stopped
from app.model_setup import fingerprint
from app.models import ModelFile, User
from app.permissions import require
from app.resources import memory_observation, release_run_locks, reserve_memory
from app.runner_client import RunnerClient
from app.runs import transition
from app.state import RunStatus
from app.task_control import lock_task


def observation(path, expected):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o222
        or info.st_size != expected.size_bytes
    ):
        raise ValueError("Verified bundle objects must remain immutable owned regular files")
    return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size


def publish_verified_models(session, entry, objects):
    files = []
    for item, path, observed in objects:
        if observation(path, item.file) != observed:
            raise ValueError("A verified bundle object changed before publication")
        relative = "models/store/" + item.file.sha256
        record = session.scalar(select(ModelFile).where(ModelFile.relative_path == relative))
        mtime = observed[2] / 1_000_000_000
        if record is None:
            record = ModelFile(
                host_path=None,
                relative_path=relative,
                sha256=item.file.sha256,
                filename=item.filename,
                size_bytes=item.file.size_bytes,
                mtime=mtime,
                format=Path(item.filename).suffix.lstrip("."),
                category="audio"
                if entry.capability in {"speech", "music", "effects"}
                else "video"
                if entry.capability in {"video", "avatar"}
                else "image",
                family=entry.family,
                capabilities=[entry.capability],
                root_label="AI Station storage",
                availability="present",
                last_seen_at=utcnow(),
            )
            session.add(record)
            session.flush()
        elif (
            record.sha256 != item.file.sha256
            or record.size_bytes != item.file.size_bytes
            or abs(record.mtime - mtime) > 0.001
        ):
            raise ValueError("The registered bundle object changed; inspect it before preparing again")
        record.availability = "present"
        record.last_seen_at = utcnow()
        files.append(
            {
                "filename": item.filename,
                "model_file_id": record.id,
                "relative_path": relative,
                "sha256": item.file.sha256,
                "size_bytes": item.file.size_bytes,
            }
        )
    return files


class BundleDownloadExecutor:
    name = "model_bundle_download"

    def execute(self, session, run):
        for permission in ("manage_models", "filesystem_read", "workspace_write", "network_read"):
            require(run.effective_permissions, permission)
        worker, claim = run.worker_id, run.claimed_at
        release = True

        def check(*, commit=True):
            session.refresh(run)
            if run.worker_id != worker or run.claimed_at != claim:
                raise LostClaim()
            cancel_expired_run(session, run.id)
            if run.owner_id:
                owner = session.get(User, run.owner_id, populate_existing=True)
                if owner is None or not owner.enabled or not owner.is_admin:
                    raise Stopped("Bundle preparation account authority changed")
            if run.status not in {"claimed", "preparing", "running"}:
                raise Stopped("Bundle preparation was stopped")
            if commit:
                session.commit()

        try:
            check()
            entry = Bundle.model_validate(run.parameters["entry"])
            if fingerprint(run.parameters["entry"]) != run.parameters["manifest_sha256"]:
                raise ValueError("The reviewed bundle manifest changed")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            session.commit()
            hardware = RunnerClient(timeout=15).hardware()
            check()
            available = (hardware.get("memory") or {}).get("available_mib")
            if not reserve_memory(session, run, available, 256):
                return DownloadExecutor.defer(
                    session, run, memory_observation(session, run, available, 256), worker=worker, claim=claim
                )
            session.commit()
            root = get_settings().data_dir
            folder = directory(root)
            needed = 0
            for item in entry.files:
                final = folder / item.file.sha256
                if final.exists() or final.is_symlink():
                    continue  # obtain still validates and hashes every cached object.
                partial = folder / (item.file.sha256 + ".part")
                existing = partial.lstat().st_size if partial.exists() and not partial.is_symlink() else 0
                needed += max(0, item.file.size_bytes - existing)
            if shutil.disk_usage(folder).free < needed + 256 * 1024**2:
                raise ValueError("Not enough application storage for all bundle files and download headroom")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            started = time.monotonic()
            completed = 0
            objects = []
            for index, item in enumerate(entry.files):
                check()
                cached = (folder / item.file.sha256).exists()

                def progress(received, total):
                    check()
                    value = {
                        "phase": "verifying" if cached or received == total else "downloading",
                        "cached_object": cached,
                        "current_file": item.filename,
                        "file_received_bytes": received,
                        "file_expected_bytes": total,
                        "received_bytes": completed + received,
                        "verified_bytes": completed,
                        "expected_bytes": entry.size_bytes,
                        "completed_files": index,
                        "file_count": len(entry.files),
                        "elapsed_seconds": max(0, time.monotonic() - started),
                    }
                    run.metadata_json = {**run.metadata_json, "model_download": value}
                    append_event(session, run.id, "model.bundle.progress", value)
                    session.commit()

                progress(0, item.file.size_bytes)
                try:
                    path = asyncio.run(obtain(root, item.file, check=check, progress=progress))
                except DownloadBusy:
                    previous = run.metadata_json.get("model_download", {})
                    result = DownloadExecutor.defer(session, run, worker=worker, claim=claim)
                    run.metadata_json = {
                        **run.metadata_json,
                        "model_download": {**previous, "phase": "waiting_for_existing_transfer"},
                    }
                    return result
                check()
                observed = observation(path, item.file)
                objects.append((item, path, observed))
                completed += item.file.size_bytes
                value = {
                    "phase": "file_verified",
                    "current_file": item.filename,
                    "received_bytes": completed,
                    "verified_bytes": completed,
                    "expected_bytes": entry.size_bytes,
                    "completed_files": index + 1,
                    "file_count": len(entry.files),
                }
                run.metadata_json = {**run.metadata_json, "model_download": value}
                append_event(session, run.id, "model.bundle.progress", value)
                session.commit()

            lock_task(session, run.task)
            check(commit=False)
            if run.task.metadata_json.get("stop_requested_at") or run.status != "running":
                raise Stopped("Bundle preparation stopped before publication")
            files = publish_verified_models(session, entry, objects)
            result = {
                "catalog_id": entry.id,
                "manifest_sha256": run.parameters["manifest_sha256"],
                "repository": entry.repository,
                "revision": entry.revision,
                "source_url": entry.source_url,
                "license": entry.license,
                "license_url": entry.license_url,
                "files": files,
                "size_bytes": completed,
                "runtime_prepared": False,
                "ready_to_try": False,
            }
            with tempfile.NamedTemporaryFile("w", suffix=".json") as receipt:
                json.dump(result, receipt)
                receipt.flush()
                register_file(
                    session,
                    source=Path(receipt.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="model-bundle-preparation.json",
                    run_id=run.id,
                    metadata={"model_bundle_preparation": True, "catalog_id": entry.id},
                )
            run.metadata_json = {
                **run.metadata_json,
                "model_file_ids": [item["model_file_id"] for item in files],
                "model_download": {
                    "phase": "files_verified",
                    "received_bytes": completed,
                    "verified_bytes": completed,
                    "expected_bytes": entry.size_bytes,
                    "completed_files": len(entry.files),
                    "file_count": len(entry.files),
                    "runtime_prepared": False,
                    "ready_to_try": False,
                },
            }
            append_event(session, run.id, "model.bundle.verified", result)
            run.summary = "All companion model files verified; runtime preparation is still required."
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            return "done"
        except LostClaim:
            release = False
            session.rollback()
            return "done"
        except Stopped:
            session.rollback()
            session.refresh(run)
            if run.worker_id != worker or run.claimed_at != claim:
                release = False
                return "done"
            if run.status in {"claimed", "preparing", "running"}:
                transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        except Exception:
            session.rollback()
            session.refresh(run)
            if run.worker_id != worker or run.claimed_at != claim:
                release = False
                return "done"
            raise
        finally:
            if release:
                release_run_locks(session, run.id)
