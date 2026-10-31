"""Worker-owned download, native adoption and inspectable shared model receipt."""

import asyncio
import json
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.model_download_files import DownloadBusy, directory, obtain
from app.model_setup import fingerprint, recommendation
from app.models import ModelDefinition, ModelFile, User
from app.permissions import require
from app.resources import RESOURCE_WAIT_KEY, memory_observation, release_run_locks, reserve_memory
from app.runner_client import RunnerClient
from app.runs import transition
from app.setup_models import Candidate
from app.state import RunStatus
from app.task_control import lock_task


class Stopped(Exception):
    pass


class LostClaim(Exception):
    pass


class DownloadExecutor:
    name = "model_download"

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
                    raise Stopped("Model preparation account authority changed")
            if run.status not in {"claimed", "preparing", "running"}:
                raise Stopped("Model preparation was stopped")
            if commit:
                session.commit()

        try:
            check()
            entry = Candidate.model_validate(run.parameters["entry"])
            if fingerprint(run.parameters["entry"]) != run.parameters["manifest_sha256"]:
                raise ValueError("The reviewed model download manifest changed")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            session.commit()
            runner = RunnerClient(timeout=30)
            hardware = runner.hardware()
            check()
            planned = recommendation(entry, hardware)
            if not planned["fits"] and not run.parameters.get("download_only", False):
                raise ValueError(
                    "This model does not fit the detected hardware. Review setup or explicitly choose download files only."
                )
            available = (hardware.get("memory") or {}).get("available_mib")
            if not reserve_memory(session, run, available, 256):
                return self.defer(
                    session, run, memory_observation(session, run, available, 256), worker=worker, claim=claim
                )
            session.commit()
            root = get_settings().data_dir
            folder = directory(root)
            partial = folder / (entry.file.sha256 + ".part")
            # The kernel separately rejects symlinks, hard links and unsafe files.
            already = partial.stat().st_size if partial.exists() and not partial.is_symlink() else 0
            final = folder / entry.file.sha256
            needed = 0 if final.exists() else max(0, entry.file.size_bytes - already)
            if shutil.disk_usage(folder).free < needed + 256 * 1024**2:
                raise ValueError("Not enough free application storage for this model and download headroom")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            started = time.monotonic()

            def progress(received, total):
                check()
                value = {
                    "phase": "verifying" if received == total else "downloading",
                    "received_bytes": received,
                    "expected_bytes": total,
                    "elapsed_seconds": max(0, time.monotonic() - started),
                }
                run.metadata_json = {**run.metadata_json, "model_download": value}
                append_event(session, run.id, "model.download.progress", value)
                session.commit()

            try:
                path = asyncio.run(obtain(root, entry.file, check=check, progress=progress))
            except DownloadBusy:
                return self.defer(session, run, worker=worker, claim=claim)
            check()
            run.metadata_json = {
                **run.metadata_json,
                "model_download": {
                    "phase": "inspecting",
                    "received_bytes": entry.file.size_bytes,
                    "expected_bytes": entry.file.size_bytes,
                },
            }
            session.commit()
            relative = "models/store/" + entry.file.sha256
            observed = path.stat()
            report = runner.verify_model(
                {
                    "run_id": run.id,
                    "host_path": relative,
                    "app_owned": True,
                    "model_sha256": entry.file.sha256,
                    "size_bytes": entry.file.size_bytes,
                    "mtime": observed.st_mtime,
                    "check_context": True,
                    "check_image": True,
                    "permissions": ["filesystem_read", "manage_models"],
                }
            )
            check()
            profile = report.get("context_profile") or {}
            per_token = (
                entry.attention_layers
                * entry.kv_heads
                * ((entry.key_length + 31) // 32 + (entry.value_length + 31) // 32)
                * 34
            )
            if not (
                report.get("present")
                and report.get("regular_file")
                and not report.get("symlink")
                and report.get("matches_observation")
                and report.get("relative_path") == relative
                and report.get("sha256") == entry.file.sha256
                and report.get("size_bytes") == entry.file.size_bytes
                and profile.get("source") == "gguf_header"
                and profile.get("architecture") == entry.architecture
                and profile.get("attention_layers") == entry.attention_layers
                and profile.get("trained_context") == entry.trained_context
                and profile.get("q8_kv_bytes_per_token") == per_token
            ):
                raise ValueError(
                    "The downloaded model does not match its native source/architecture inspection"
                )
            image_present = bool(report.get("image", {}).get("present"))
            if report.get("error") and image_present:
                raise ValueError("Native model inspection did not succeed")
            preset = recommendation(entry, hardware)
            # Stop and registry/receipt publication use the same task fence.
            lock_task(session, run.task)
            check(commit=False)
            if run.task.metadata_json.get("stop_requested_at") or run.status != "running":
                raise Stopped("Model preparation stopped before registration")
            if run.owner_id:
                owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
                if owner is None or not owner.enabled or not owner.is_admin:
                    raise Stopped("Model preparation account authority changed before registration")
            file = session.scalar(select(ModelFile).where(ModelFile.relative_path == relative))
            if file is None:
                file = ModelFile(
                    host_path=None,
                    relative_path=relative,
                    sha256=entry.file.sha256,
                    filename=entry.filename,
                    size_bytes=entry.file.size_bytes,
                    mtime=report["mtime"],
                    format="gguf",
                    category="llm",
                    family="qwen3",
                    quantization=entry.quantization,
                    capabilities=["chat"],
                    root_label="AI Station storage",
                    availability="present",
                    last_seen_at=utcnow(),
                )
                session.add(file)
                session.flush()
            elif (
                file.sha256 != entry.file.sha256
                or file.size_bytes != entry.file.size_bytes
                or abs(file.mtime - report["mtime"]) > 0.001
            ):
                raise ValueError(
                    "The installed model registry observation changed; inspect it before replacing anything"
                )
            definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == file.id))
            if definition is None:
                definition = ModelDefinition(
                    file_id=file.id,
                    name=entry.name,
                    category="llm",
                    family="qwen3",
                    capabilities=["chat"],
                    status="registered" if image_present else "downloaded",
                    last_verify_run_id=run.id,
                    metadata_json={
                        "gpus": preset["gpus"],
                        "context_size": preset.get("context_size") or 4096,
                        "cache_type": "q8_0",
                        "context_profile": profile,
                        "catalog_id": entry.id,
                        "catalog_manifest_sha256": run.parameters["manifest_sha256"],
                        "source_sha256": entry.file.sha256,
                    },
                )
                session.add(definition)
                session.flush()
            result = {
                "catalog_id": entry.id,
                "manifest_sha256": run.parameters["manifest_sha256"],
                "model_file_id": file.id,
                "definition_id": definition.id,
                "relative_path": relative,
                "sha256": entry.file.sha256,
                "size_bytes": entry.file.size_bytes,
                "license": entry.license,
                "license_url": entry.license_url,
                "source_url": entry.source_url,
                "source_revision": entry.revision,
                "context_profile": profile,
                "runtime_image_present": image_present,
                "ready_to_try": bool(image_present and preset["fits"]),
                "preset": preset,
            }
            with tempfile.NamedTemporaryFile("w", suffix=".json") as receipt:
                json.dump(result, receipt)
                receipt.flush()
                register_file(
                    session,
                    source=Path(receipt.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="model-preparation.json",
                    run_id=run.id,
                    metadata={"catalog_model_preparation": True, "model_file_id": file.id},
                )
            run.metadata_json = {
                **run.metadata_json,
                "model_file_id": file.id,
                "model_download": {
                    "phase": "files_verified",
                    "received_bytes": entry.file.size_bytes,
                    "expected_bytes": entry.file.size_bytes,
                    "ready_to_try": result["ready_to_try"],
                    "runtime_image_present": image_present,
                    "preset": preset,
                },
            }
            append_event(session, run.id, "model.download.verified", result)
            run.summary = "Model files downloaded and verified; " + (
                "ready to try in Chat."
                if result["ready_to_try"]
                else "runtime/hardware setup is still needed before inference."
            )
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

    @staticmethod
    def defer(session, run, memory=None, *, worker, claim):
        lock_task(session, run.task)
        session.refresh(run)
        if run.worker_id != worker or run.claimed_at != claim:
            raise LostClaim()
        if run.task.metadata_json.get("stop_requested_at") or run.status == "cancel_requested":
            raise Stopped("Model preparation stopped before deferral")
        run.task.metadata_json = {
            **run.task.metadata_json,
            RESOURCE_WAIT_KEY: (utcnow() + timedelta(seconds=5)).isoformat(),
        }
        if memory is not None:
            run.metadata_json = {
                **run.metadata_json,
                "resource_wait": {"reason": "memory", "checked_at": utcnow().isoformat(), **memory},
            }
        else:
            run.metadata_json = {
                **run.metadata_json,
                "model_download": {"phase": "waiting_for_existing_transfer"},
            }
        transition(
            session,
            run,
            RunStatus.INTERRUPTED,
            event_type="run.interrupted",
            payload={"reason": "Waiting for model download resources"},
        )
        transition(session, run, RunStatus.QUEUED, event_type="run.requeued")
        run.finished_at = run.worker_id = run.lease_expires_at = None
        return "requeued"
