"""Image model inputs and OCI preparation through the existing owned supervisor."""

import json
import re
import tempfile
from pathlib import Path

from app.artifacts import register_file
from app.bundle_download_job import publish_verified_models
from app.config import get_settings
from app.events import append_event
from app.image_setup_client import ImageSetupClient
from app.model_bundles import Bundle, BundleFile
from app.runs import transition
from app.runtime_setup_api import IMAGE_PROFILE, PERMISSIONS
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec
from app.state import RunStatus


def model_bundle(recipe):
    inputs = recipe["inputs"]
    primary = next(v for v in inputs if v.get("role") == "diffusion")
    return Bundle(
        id="qwen-image21-q4-companions-v1",
        name=recipe["name"],
        capability="image",
        family="qwen_image21",
        license="Qwen Research",
        license_url=recipe["license_url"],
        repository=primary["repository"],
        revision=primary["revision"],
        source_url=f"https://huggingface.co/{primary['repository']}/tree/{primary['revision']}",
        files=tuple(BundleFile(filename=v["filename"], file=file_spec(v)) for v in inputs),
    )


class ImageSetupExecutor(SpeechSetupExecutor):
    name = "image_setup"
    metadata_prefix = "image"
    setup_label = "image"
    storage_headroom_bytes = 2 * 1024**3

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") != IMAGE_PROFILE
            or len(inputs) != 4
            or {v.get("role") for v in inputs} != {"diffusion", "text_encoder", "vision_projector", "vae"}
            or any(v.get("kind") != "model" for v in inputs)
            or not re.fullmatch(r"[a-f0-9]{64}", recipe.get("model_manifest_sha256", ""))
        ):
            raise ValueError("Image setup requires its complete reviewed companion manifest")
        model_bundle(recipe)

    def runner(self):
        return ImageSetupClient(timeout=30)

    def payload(self, run):
        return {
            "run_id": run.id,
            "profile": IMAGE_PROFILE,
            "manifest_sha256": run.parameters["manifest_sha256"],
            "deadline_at": run.metadata_json["image_native_deadline_at"],
            "permissions": PERMISSIONS,
        }

    def progress(self, run, value):
        if not isinstance(value, dict):
            return None
        models = sum(v["size_bytes"] for v in run.parameters["recipe"]["inputs"])
        previous = (run.metadata_json.get("runtime_preparation") or {}).get("received_bytes", models)
        normalized = {**value, "received_bytes": value.get("received_bytes", max(0, previous - models))}
        progress = RuntimeSetupExecutor.progress(self, run, normalized)
        if progress is None:
            return None
        return {
            **progress,
            "phase": "runtime_" + progress["phase"],
            "received_bytes": models + progress["received_bytes"],
            "expected_bytes": models + progress["expected_bytes"],
            "verified_model_bytes": models,
        }

    def complete(self, session, run, result, runner):
        recipe = run.parameters["recipe"]
        image = result.get("image") or {}
        if (
            image.get("reference") != recipe["image_reference"]
            or image.get("platform") != "linux/amd64"
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(image.get("id", "")))
        ):
            raise ValueError("The prepared image engine does not match the reviewed source")
        root = get_settings().data_dir
        entry = model_bundle(recipe)
        observed = run.metadata_json.get("image_model_observations") or {}
        files = publish_verified_models(
            session,
            entry,
            [(v, root / "models/store" / v.file.sha256, tuple(observed[v.file.sha256])) for v in entry.files],
        )
        receipt = {
            "profile": IMAGE_PROFILE,
            "manifest_sha256": run.parameters["manifest_sha256"],
            "model_manifest_sha256": recipe["model_manifest_sha256"],
            "image": image,
            "model_files": files,
            "runtime_prepared": True,
            "image_inference_tested": False,
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json") as output:
            json.dump(receipt, output)
            output.flush()
            register_file(
                session,
                source=Path(output.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="image-runtime-preparation.json",
                run_id=run.id,
                metadata={"runtime_preparation": True, "image_setup": True},
            )
        total = sum(v["size_bytes"] for v in recipe["inputs"]) + recipe["download_bytes"]
        run.metadata_json = {
            **run.metadata_json,
            "runtime_preparation": {
                "phase": "image_environment_prepared",
                "received_bytes": total,
                "expected_bytes": total,
                "model_file_ids": [v["model_file_id"] for v in files],
                "image_inference_tested": False,
            },
        }
        run.summary = "Image engine and model files prepared. Generate a first image to check the result."
        append_event(session, run.id, "runtime.image.prepared", receipt)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
