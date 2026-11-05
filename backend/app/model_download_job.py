"""Worker-owned download, native adoption and inspectable shared model receipt."""

import asyncio
import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.download_storage import DownloadStorage
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.hub_candidates import download_candidate
from app.model_download_files import DownloadBusy, directory, obtain
from app.model_setup import fingerprint, recommendation
from app.models import ModelDefinition, ModelFile, User
from app.permissions import require
from app.resources import RESOURCE_WAIT_KEY, memory_observation, release_run_locks, reserve_memory
from app.runner_client import RunnerClient
from app.runs import transition
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
        storage = None

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
            if storage is not None:
                storage.check()
            if commit:
                session.commit()

        try:
            check()
            entry = download_candidate(run.parameters["entry"])
            if fingerprint(run.parameters["entry"]) != run.parameters["manifest_sha256"]:
                raise ValueError("The reviewed model download manifest changed")
            split = getattr(entry, "origin", None) == "hub_split"
            if split:
                from app.hub_split_candidates import INSTALLATION_QUALIFIED

                if not INSTALLATION_QUALIFIED:
                    raise ValueError("Complete GGUF source installation is still being qualified")
            from app.gguf_bindings import candidate_size, transfer_files

            download_specs = transfer_files(entry)
            total_size = candidate_size(entry)
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            session.commit()
            runner = RunnerClient(timeout=30)
            hardware = runner.hardware()
            check()
            from app.native_models import active_environment, host_profile, native, ready, verification

            is_native = native(entry.model_dump())
            if is_native and entry.runtime_profile != host_profile(hardware):
                raise ValueError("Choose the native model profile for this Mac before downloading")
            environment_id = active_environment(entry.runtime_profile) if is_native else None
            native_preset = {
                "runtime_profile": entry.runtime_profile,
                "context_size": 4096,
                "environment_id": environment_id,
            }
            if getattr(entry, "origin", None) == "hub_avatar":
                from app.hub_avatar_candidates import AvatarReadinessPending, refresh_plan

                try:
                    current = refresh_plan(entry, check, require_engine=True)
                except AvatarReadinessPending:
                    return self.defer(
                        session, run, worker=worker, claim=claim, phase="checking_avatar_engine"
                    )
                if not current.preparation_available or not recommendation(current, hardware)["fits"]:
                    raise ValueError("The avatar runtime or hardware changed before transferring weights")
            planned = recommendation(entry, hardware)
            if not planned["fits"] and not run.parameters.get("download_only", False):
                raise ValueError(
                    "This model does not fit the detected hardware. Review setup or explicitly choose download files only."
                )
            available = (hardware.get("memory") or {}).get("available_mib")
            if entry.capability == "embedding":
                from app.control_memory import available_mib

                container_available = available_mib()
                available = (
                    min(available, container_available)
                    if type(available) in {int, float} and container_available is not None
                    else None
                )
            memory_mib = 2048 if entry.capability == "embedding" else 256
            if not reserve_memory(session, run, available, memory_mib):
                return self.defer(
                    session,
                    run,
                    memory_observation(session, run, available, memory_mib),
                    worker=worker,
                    claim=claim,
                )
            session.commit()
            root = get_settings().data_dir
            folder = directory(root)
            partial = folder / (entry.file.sha256 + ".part")
            # The kernel separately rejects symlinks, hard links and unsafe files.
            final = folder / entry.file.sha256

            def remaining():
                if entry.capability == "embedding" or split:
                    total = 0
                    specs = (
                        (entry.file, entry.tokenizer) if entry.capability == "embedding" else download_specs
                    )
                    for spec in specs:
                        object_path, partial_path = folder / spec.sha256, folder / (spec.sha256 + ".part")
                        already = (
                            partial_path.stat().st_size
                            if partial_path.exists() and not partial_path.is_symlink()
                            else 0
                        )
                        total += 0 if object_path.exists() else max(0, spec.size_bytes - already)
                    return total
                already = partial.stat().st_size if partial.exists() and not partial.is_symlink() else 0
                return 0 if final.exists() else max(0, entry.file.size_bytes - already)

            storage = DownloadStorage(folder, hardware, runner, remaining)
            storage.check()
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

            def recovered(url):
                check()
                append_event(
                    session,
                    run.id,
                    "model.download.source_refreshed",
                    {"sha256": entry.file.sha256, "source_url": url},
                )
                session.commit()

            try:
                path = asyncio.run(
                    obtain(
                        root,
                        entry.file,
                        check=check,
                        progress=(
                            lambda received, total: progress(
                                received, entry.file.size_bytes + entry.tokenizer.size_bytes
                            )
                        )
                        if entry.capability == "embedding"
                        else (lambda received, total: progress(received, total_size))
                        if split
                        else progress,
                        source_recovered=recovered,
                    )
                )
                if split:
                    received_before = entry.file.size_bytes
                    for spec in download_specs[1:]:
                        check()

                        def part_progress(received, total, base=received_before):
                            progress(base + received, total_size)

                        def part_recovered(url, digest=spec.sha256):
                            check()
                            append_event(
                                session,
                                run.id,
                                "model.download.source_refreshed",
                                {"sha256": digest, "source_url": url},
                            )
                            session.commit()

                        asyncio.run(
                            obtain(
                                root,
                                spec,
                                check=check,
                                progress=part_progress,
                                source_recovered=part_recovered,
                            )
                        )
                        received_before += spec.size_bytes
            except DownloadBusy:
                return self.defer(session, run, worker=worker, claim=claim)
            check()
            bundle = None
            if split:
                from app.gguf_bindings import OwnedBundle

                bundle = OwnedBundle(
                    parts=[
                        {
                            "sha256": spec.sha256,
                            "size_bytes": spec.size_bytes,
                            "mtime": (folder / spec.sha256).stat().st_mtime,
                        }
                        for spec in download_specs
                    ]
                )
            if entry.capability == "embedding":
                from app.hub_embedding_install import adopt

                try:
                    return adopt(session, run, entry, path, check, progress, recovered, obtain)
                except DownloadBusy:
                    return self.defer(session, run, worker=worker, claim=claim)
            run.metadata_json = {
                **run.metadata_json,
                "model_download": {
                    "phase": "inspecting",
                    "received_bytes": total_size,
                    "expected_bytes": total_size,
                },
            }
            session.commit()
            if entry.capability == "avatar":
                from app.hub_avatar_candidates import AvatarReadinessPending
                from app.hub_avatar_install import adopt as adopt_avatar

                try:
                    return adopt_avatar(session, run, entry, path, runner, hardware, check)
                except AvatarReadinessPending:
                    return self.defer(
                        session, run, worker=worker, claim=claim, phase="checking_avatar_engine"
                    )
            if entry.capability == "music":
                from app.hub_music_install import adopt as adopt_music

                return adopt_music(session, run, entry, path, runner, hardware, check)
            if entry.capability == "speech":
                from app.hub_speech_install import adopt as adopt_speech

                return adopt_speech(session, run, entry, path, runner, hardware, check)
            if entry.capability == "video":
                from app.hub_video_install import adopt as adopt_video

                return adopt_video(session, run, entry, path, runner, hardware, check)
            if entry.capability == "image":
                from app.hub_image_install import adopt

                return adopt(session, run, entry, path, runner, hardware, check)
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
                    **({"model_bundle": bundle.model_dump(mode="json")} if bundle else {}),
                    **({"runtime_profile": entry.runtime_profile} if entry.runtime_profile else {}),
                    **(verification(native_preset) if is_native else {}),
                    **({"allow_unprepared_sdk": True} if is_native and environment_id is None else {}),
                    "permissions": ["filesystem_read", "manage_models"],
                }
            )
            check()
            profile = report.get("context_profile") or {}
            bundle_metadata = {}
            if bundle:
                from app.gguf_bindings import checked_proof

                proof = checked_proof(bundle, report.get("model_bundle"))
                if proof.get("context_profile") != profile:
                    raise ValueError("The complete bundle and primary context observations disagree")
                bundle_metadata = {
                    "model_bundle": bundle.model_dump(mode="json"),
                    "bundle_proof": proof,
                    "source_parts": [
                        {
                            "filename": part.filename,
                            "sha256": part.file.sha256,
                            "size_bytes": part.file.size_bytes,
                        }
                        for part in entry.parts
                    ],
                }
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
                and type(profile.get("trained_context")) is int
                and 512 <= profile["trained_context"] <= 16777216
                and profile.get("q8_kv_bytes_per_token") == per_token
                and profile.get("state_reserve_mib", 0) == entry.state_reserve_mib
            ):
                raise ValueError(
                    "The downloaded model does not match its native source/architecture inspection"
                )
            reviewed_context = 4096 if entry.runtime_profile else entry.context_ceiling
            if profile["trained_context"] < reviewed_context:
                raise ValueError(
                    f"The model file supports only {profile['trained_context']} tokens, below the reviewed {reviewed_context}-token limit; review a smaller context before using these cached files"
                )
            context_metadata = {}
            if profile["trained_context"] != entry.trained_context:
                context_metadata = {
                    "context_notice": f"The model file declares {profile['trained_context']:,} context tokens; publisher configuration declares {entry.trained_context:,}. The initial preset stays within the reviewed {reviewed_context:,}-token limit."
                }
                append_event(
                    session,
                    run.id,
                    "model.context.reviewed",
                    {
                        "file_context": profile["trained_context"],
                        "publisher_context": entry.trained_context,
                        "reviewed_limit": reviewed_context,
                    },
                )
            if entry.runtime_profile:
                from app.cpu_models import estimate

                if report.get("cpu") != {
                    "runtime_profile": entry.runtime_profile,
                    "ram_mib": estimate(entry),
                    "context_size": 4096,
                }:
                    raise ValueError("The native CPU profile/budget differs from the reviewed model")
            image_present = bool((report.get("image") or {}).get("present"))
            runtime_present = ready(report, native_preset) if is_native else image_present
            if report.get("error") and runtime_present:
                raise ValueError("Native model inspection did not succeed")
            preset = recommendation(entry, hardware)
            if bundle:
                from app.hub_split_candidates import recommendation as bundle_recommendation

                preset = bundle_recommendation(entry, hardware, proof)
                if not preset["fits"]:
                    raise ValueError(
                        "Verified complete tensor placement and useful context do not fit this hardware; downloaded files were preserved"
                    )
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
                    filename=(entry.filename.rsplit("-", 3)[0] + ".gguf") if split else entry.filename,
                    size_bytes=entry.file.size_bytes,
                    # Keep the exact accepted bundle coordinate. Native and
                    # container filesystem views may legitimately differ within
                    # the verifier's 1-ms observation tolerance.
                    mtime=bundle.parts[0].mtime if bundle else report["mtime"],
                    format="gguf",
                    category="llm",
                    family=entry.architecture,
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
            from app.gguf_bindings import content_key
            from app.model_selection import default_definition, selection_id

            default = default_definition(session, file.id)
            key = content_key(bundle.model_dump(mode="json")) if bundle else None
            definition = default
            if bundle:
                definition = next(
                    (
                        item
                        for item in session.scalars(
                            select(ModelDefinition).where(ModelDefinition.file_id == file.id)
                        )
                        if (item.metadata_json or {}).get("model_bundle")
                        and content_key(item.metadata_json["model_bundle"]) == key
                    ),
                    None,
                )
            if definition is not None:
                from app.cpu_models import compatible

                if not compatible(definition, entry):
                    raise ValueError(
                        "These model files already have a different runtime preset; use the existing model configuration"
                    )
                if (definition.metadata_json or {}).get("model_bundle") != bundle_metadata.get(
                    "model_bundle"
                ):
                    raise ValueError("The existing model has a different complete object binding")
            if definition is None:
                definition = ModelDefinition(
                    file_id=file.id,
                    binding_key=key if bundle and default is not None else None,
                    name=entry.name,
                    category="llm",
                    family=entry.architecture,
                    capabilities=["chat"],
                    status="registered" if runtime_present else "downloaded",
                    last_verify_run_id=run.id,
                    metadata_json={
                        "gpus": preset["gpus"],
                        "context_size": preset.get("context_size") or 4096,
                        "cache_type": "q8_0",
                        "context_profile": profile,
                        **(
                            {"runtime_profile": entry.runtime_profile, "ram_mib": preset["ram_mib"]}
                            if entry.runtime_profile
                            else {}
                        ),
                        **({"environment_id": environment_id} if is_native and environment_id else {}),
                        "catalog_id": entry.id,
                        "catalog_manifest_sha256": run.parameters["manifest_sha256"],
                        "source_sha256": entry.file.sha256,
                        **bundle_metadata,
                        **context_metadata,
                    },
                )
                session.add(definition)
                session.flush()
            if bundle and definition.status == "removed":
                definition.status = "registered" if runtime_present else "downloaded"
                definition.updated_at = utcnow()
            result = {
                "catalog_id": entry.id,
                "manifest_sha256": run.parameters["manifest_sha256"],
                "model_file_id": file.id,
                "definition_id": definition.id,
                "model_key": "llamacpp:" + selection_id(file, definition),
                "relative_path": relative,
                "sha256": entry.file.sha256,
                "size_bytes": entry.file.size_bytes,
                "license": entry.license,
                "license_url": entry.license_url,
                "source_url": entry.source_url,
                "source_revision": entry.revision,
                "context_profile": profile,
                "runtime_image_present": image_present,
                "runtime_present": runtime_present,
                "ready_to_try": bool(
                    runtime_present and preset["fits"] and definition.status == "registered"
                ),
                "preset": preset,
                **({"model_size_bytes": total_size, **bundle_metadata} if bundle else {}),
                **context_metadata,
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
                "model_key": result["model_key"],
                "definition_id": definition.id,
                "model_download": {
                    "phase": "files_verified",
                    "received_bytes": total_size,
                    "expected_bytes": total_size,
                    "ready_to_try": result["ready_to_try"],
                    "runtime_image_present": image_present,
                    "runtime_present": runtime_present,
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
    def defer(session, run, memory=None, *, worker, claim, phase="waiting_for_existing_transfer"):
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
                "model_download": {"phase": phase},
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
