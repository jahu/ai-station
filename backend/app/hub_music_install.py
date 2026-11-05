"""Native graph and complete engine admission before shared music registration."""

import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.hub_music_candidates import recommendation
from app.models import ModelDefinition, ModelFile, User
from app.music_setup_client import MusicSetupClient
from app.runs import transition
from app.state import RunStatus
from app.task_control import lock_task


def adopt(session, run, entry, path, runner, hardware, check):
    from app.model_download_job import Stopped

    observed = path.stat()
    relative = "models/store/" + entry.file.sha256
    report = runner.verify_model(
        {
            "run_id": run.id,
            "host_path": relative,
            "app_owned": True,
            "model_sha256": entry.file.sha256,
            "size_bytes": entry.file.size_bytes,
            "mtime": observed.st_mtime,
            "checkpoint_profile": entry.slot["profile"],
            "permissions": ["filesystem_read", "manage_models"],
        }
    )
    check()
    proof = report.get("checkpoint_profile") or {}
    if not (
        report.get("present")
        and report.get("regular_file")
        and not report.get("symlink")
        and report.get("matches_observation")
        and not report.get("error")
        and report.get("relative_path") == relative
        and report.get("sha256") == entry.file.sha256
        and report.get("size_bytes") == entry.file.size_bytes
        and proof.get("source") == "safetensors_descriptors"
        and proof.get("header_sha256") == entry.configuration_sha256
        and all(
            proof.get(k) == entry.slot[k]
            for k in ("profile", "runtime_profile", "role", "tensor_count", "schema_sha256")
        )
    ):
        raise ValueError("The downloaded music graph differs from its reviewed native checkpoint slot")
    catalog = MusicSetupClient(timeout=20).runtime_setup_catalog()
    check()
    managed = catalog.get("managed_music") or {}
    if catalog.get("manifest_sha256") != entry.setup_manifest_sha256 or managed.get("available") is not True:
        raise ValueError("The reviewed music engine and companions are not ready; inspect preparation")
    runtime = managed.get("managed_runtime") or {}
    if (
        runtime.get("profile") != entry.slot["runtime_profile"]
        or runtime.get("manifest_sha256") != entry.setup_manifest_sha256
    ):
        raise ValueError("The prepared music environment differs from its reviewed recipe")
    if not recommendation(entry, hardware)["fits"]:
        raise ValueError("The music hardware profile changed before registration")
    lock_task(session, run.task)
    check(commit=False)
    if (run.task.metadata_json.get("model_download") or {}).get("license_accepted") is not True:
        raise ValueError("The music model and complete fixed components need explicit license acceptance")
    if run.task.metadata_json.get("stop_requested_at") or run.status != "running":
        raise Stopped("Music installation stopped before publication")
    if run.owner_id:
        owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
        if owner is None or not owner.enabled or not owner.is_admin:
            raise Stopped("Music installation administrator authority changed")
    current = path.stat()
    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
        observed.st_dev,
        observed.st_ino,
        observed.st_size,
        observed.st_mtime_ns,
    ):
        raise ValueError("The verified music object changed before registration")
    file = session.scalar(select(ModelFile).where(ModelFile.relative_path == relative))
    if file is None:
        file = ModelFile(
            host_path=None,
            relative_path=relative,
            sha256=entry.file.sha256,
            filename=entry.filename,
            size_bytes=entry.file.size_bytes,
            mtime=report["mtime"],
            format="safetensors",
            category="audio",
            family=entry.architecture,
            quantization=entry.quantization,
            capabilities=["music"],
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
        or file.category != "audio"
    ):
        raise ValueError("The registered music object changed; inspect it before replacing anything")
    binding = {
        "checkpoint_profile": entry.slot["profile"],
        "schema_sha256": entry.slot["schema_sha256"],
        "managed_runtime": dict(runtime),
        "cpu_offload": True,
        "ram_mib": 18432,
        "minimum_physical_ram_mib": 24576,
        "minimum_vram_mib": 12288,
        "maximum_seconds": 600,
    }
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == file.id))
    if definition is not None and (
        definition.category != "audio" or definition.metadata_json.get("music", {}).get("binding") != binding
    ):
        raise ValueError("This checkpoint already has a different music runtime binding")
    if definition is None:
        definition = ModelDefinition(
            name=entry.name,
            file_id=file.id,
            category="audio",
            family=entry.architecture,
            capabilities=["music"],
            status="registered",
            last_verify_run_id=run.id,
            metadata_json={
                "music": {"sha256": entry.file.sha256, "binding": binding},
                "source": entry.model_dump(mode="json"),
                "native_checkpoint": proof,
                "locally_qualified": False,
            },
        )
        session.add(definition)
        session.flush()
    result = {
        "model_file_id": file.id,
        "definition_id": definition.id,
        "capability": "music",
        "relative_path": relative,
        "sha256": entry.file.sha256,
        "source_revision": entry.revision,
        "source_url": entry.source_url,
        "native_checkpoint": proof,
        "binding": binding,
        "ready_to_try": True,
        "locally_qualified": False,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as receipt:
        json.dump(result, receipt)
        receipt.flush()
        register_file(
            session,
            source=Path(receipt.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="music-model-preparation.json",
            run_id=run.id,
            metadata={"music_model_preparation": True, "model_file_id": file.id},
        )
    run.metadata_json = {
        **run.metadata_json,
        "model_file_id": file.id,
        "definition_id": definition.id,
        "model_download": {
            "phase": "files_verified",
            "received_bytes": entry.file.size_bytes,
            "expected_bytes": entry.file.size_bytes,
            "ready_to_try": True,
        },
    }
    append_event(session, run.id, "model.download.verified", result)
    run.summary = "Music checkpoint and complete native engine verified; ready to try in Music."
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
    return "done"
