"""Adopt a new image checkpoint only after native slot and engine verification."""

import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.hub_image_candidates import recommendation
from app.image_setup_client import ImageSetupClient
from app.models import ModelDefinition, ModelFile, User
from app.runs import transition
from app.state import RunStatus
from app.task_control import lock_task


def adopt(session, run, entry, path, runner, hardware, check):
    from app.model_download_job import Stopped

    observed = path.stat()
    relative = "models/store/" + entry.file.sha256
    native = runner.verify_model(
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
    proof = native.get("checkpoint_profile") or {}
    if not (
        native.get("present")
        and native.get("regular_file")
        and not native.get("symlink")
        and native.get("matches_observation")
        and native.get("relative_path") == relative
        and native.get("sha256") == entry.file.sha256
        and native.get("size_bytes") == entry.file.size_bytes
        and not native.get("error")
        and proof.get("source") == "gguf_tensor_descriptors"
        and all(
            proof.get(k) == entry.slot[k]
            for k in ("profile", "runtime_profile", "role", "tensor_count", "schema_sha256")
        )
    ):
        raise ValueError("The downloaded image graph differs from the reviewed native checkpoint slot")
    catalog = ImageSetupClient(timeout=20).runtime_setup_catalog()
    check()
    if catalog.get("manifest_sha256") != entry.setup_manifest_sha256 or not (
        catalog.get("managed_images") or {}
    ).get("available"):
        raise ValueError(
            "The reviewed image engine and companions are not ready; inspect preparation before resuming"
        )
    preset = recommendation(entry, hardware)
    if not preset["fits"]:
        raise ValueError("The image hardware profile changed before registration")
    lock_task(session, run.task)
    check(commit=False)
    if run.task.metadata_json.get("stop_requested_at") or run.status != "running":
        raise Stopped("Image installation stopped before publication")
    if run.owner_id:
        owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
        if owner is None or not owner.enabled or not owner.is_admin:
            raise Stopped("Image installation administrator authority changed")
    current = path.stat()
    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
        observed.st_dev,
        observed.st_ino,
        observed.st_size,
        observed.st_mtime_ns,
    ):
        raise ValueError("The verified image object changed before registration")
    file = session.scalar(select(ModelFile).where(ModelFile.relative_path == relative))
    if file is None:
        file = ModelFile(
            host_path=None,
            relative_path=relative,
            sha256=entry.file.sha256,
            filename=entry.filename,
            size_bytes=entry.file.size_bytes,
            mtime=native["mtime"],
            format="gguf",
            category="image",
            family=entry.architecture,
            quantization=entry.quantization,
            capabilities=["image"],
            root_label="AI Station storage",
            availability="present",
            last_seen_at=utcnow(),
        )
        session.add(file)
        session.flush()
    elif (
        file.sha256 != entry.file.sha256
        or file.size_bytes != entry.file.size_bytes
        or abs(file.mtime - native["mtime"]) > 0.001
        or file.category != "image"
    ):
        raise ValueError("The registered image object changed; inspect it before replacing anything")
    binding = {
        "checkpoint_profile": entry.slot["profile"],
        "schema_sha256": entry.slot["schema_sha256"],
        "runtime_profile": entry.slot["runtime_profile"],
        "manifest_sha256": entry.setup_recipe["model_manifest_sha256"],
        "gpu_count": len(preset["gpus"]),
        "ram_mib": preset["ram_mib"],
        "minimum_primary_vram_mib": preset["primary_vram_mib"],
        "minimum_companion_vram_mib": preset["companion_vram_mib"],
        "maximum_side": preset["maximum_side"],
    }
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == file.id))
    if definition is not None and (
        definition.category != "image" or definition.metadata_json.get("image", {}).get("binding") != binding
    ):
        raise ValueError("This checkpoint already has a different image runtime binding")
    if definition is None:
        definition = ModelDefinition(
            name=entry.name,
            file_id=file.id,
            category="image",
            family=entry.architecture,
            capabilities=["t2i", "img2img", "recompose"],
            status="registered",
            last_verify_run_id=run.id,
            metadata_json={
                "image": {
                    "backend": "qwen",
                    "sha256": entry.file.sha256,
                    "modes": ["t2i", "img2img", "recompose"],
                    "binding": binding,
                    "presets": {
                        "t2i": {"width": 832, "height": 1024},
                        "img2img": {"max_side": 1024},
                        "recompose": {"width": 832, "height": 1024},
                    },
                    "license_url": entry.license_url,
                },
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
        "capability": "image",
        "manifest_sha256": run.parameters["manifest_sha256"],
        "source_url": entry.source_url,
        "source_revision": entry.revision,
        "relative_path": relative,
        "sha256": entry.file.sha256,
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
            original_filename="image-model-preparation.json",
            run_id=run.id,
            metadata={"image_model_preparation": True, "model_file_id": file.id},
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
    run.summary = "Image checkpoint and complete engine verified; ready to try in Images."
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
    return "done"
