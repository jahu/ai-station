"""Speech inputs and receipt reuse the ordinary owned native-setup supervisor."""

import asyncio
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from app.bundle_download_job import observation, publish_verified_models
from app.config import get_settings
from app.db import utcnow
from app.download_storage import DownloadStorage
from app.events import append_event
from app.model_bundles import Bundle, BundleFile
from app.model_download_files import DownloadBusy, FileSpec, directory, obtain
from app.model_download_job import DownloadExecutor, Stopped
from app.model_download_job import LostClaim as DownloadLostClaim
from app.runtime_setup_api import PERMISSIONS, SPEECH_PROFILE
from app.runtime_setup_job import LostClaim, RuntimeSetupExecutor
from app.speech_setup_client import SpeechSetupClient


def file_spec(item):
    return FileSpec(sha256=item["sha256"], size_bytes=item["size_bytes"], urls=(item["url"],))


def model_bundle(recipe):
    revision = recipe["model_revision"]
    repository = "ResembleAI/chatterbox"
    return Bundle(
        id="chatterbox-multilingual-v3-weights-v1",
        name="Chatterbox Multilingual · v3 model files",
        repository=repository,
        revision=revision,
        license_url=recipe["model_license_url"],
        source_url=f"https://huggingface.co/{repository}/tree/{revision}",
        files=tuple(
            BundleFile(filename=v["filename"], file=file_spec(v))
            for v in recipe["inputs"]
            if v["kind"] == "model"
        ),
    )


class SpeechSetupExecutor(RuntimeSetupExecutor):
    name = "speech_setup"
    ram_mib = 4096
    metadata_prefix = "speech"
    setup_label = "speech"
    storage_headroom_bytes = 8 * 1024**3
    required_permissions = [*PERMISSIONS, "filesystem_read"]

    def validate(self, run):
        super().validate(run)
        if run.parameters.get("profile") != SPEECH_PROFILE:
            raise ValueError("Speech setup requires its fixed reviewed runtime profile")
        recipe = run.parameters["recipe"]
        if not 1 <= len(recipe["inputs"]) <= 192 or len({v["sha256"] for v in recipe["inputs"]}) != len(
            recipe["inputs"]
        ):
            raise ValueError("Invalid reviewed speech input manifest")
        model_bundle(recipe)

    def runner(self):
        return SpeechSetupClient(timeout=30)

    def payload(self, run):
        return {
            "run_id": run.id,
            "profile": SPEECH_PROFILE,
            "manifest_sha256": run.parameters["manifest_sha256"],
            "deadline_at": run.metadata_json["speech_native_deadline_at"],
            "permissions": PERMISSIONS,
        }

    def before_native(self, session, run, check):
        recipe = run.parameters["recipe"]
        root = get_settings().data_dir
        folder = directory(root)
        worker, claim = run.worker_id, run.claimed_at
        inputs = [(item, file_spec(item)) for item in recipe["inputs"]]
        total = sum(spec.size_bytes for _, spec in inputs)
        completed = 0
        observed_models = {}
        storage = None

        def remaining():
            total = 0
            for _, spec in inputs:
                if (folder / spec.sha256).exists():
                    continue
                partial = folder / (spec.sha256 + ".part")
                received = partial.stat().st_size if partial.exists() and not partial.is_symlink() else 0
                total += max(0, spec.size_bytes - received)
            return total

        def alive():
            if check():
                raise Stopped(f"{self.setup_label.capitalize()} preparation was stopped")
            if storage is not None:
                storage.check()

        try:
            alive()
            runner = self.runner()
            hardware = runner.hardware()
            alive()
            storage = DownloadStorage(
                folder, hardware, runner, remaining, headroom_bytes=self.storage_headroom_bytes
            )
            storage.check()
            for index, (item, spec) in enumerate(inputs):
                alive()
                cached = (folder / spec.sha256).exists()

                def progress(received, expected):
                    alive()
                    value = {
                        "phase": "verifying_files" if cached or received == expected else "downloading_files",
                        "cached_object": cached,
                        "current_file": item["filename"],
                        "received_bytes": completed + received,
                        "expected_bytes": total,
                        "verified_bytes": completed,
                        "completed_files": index,
                        "file_count": len(inputs),
                    }
                    run.metadata_json = {**run.metadata_json, "runtime_preparation": value}
                    append_event(session, run.id, "runtime.prepare.progress", value)
                    session.commit()

                def recovered(url):
                    alive()
                    append_event(
                        session,
                        run.id,
                        "model.download.source_refreshed",
                        {"sha256": spec.sha256, "filename": item["filename"], "source_url": url},
                    )
                    session.commit()

                path = asyncio.run(
                    obtain(root, spec, check=alive, progress=progress, source_recovered=recovered)
                )
                alive()
                if item["kind"] == "model":
                    observed_models[spec.sha256] = list(observation(path, spec))
                completed += spec.size_bytes
            run.metadata_json = {
                **run.metadata_json,
                f"{self.metadata_prefix}_model_observations": observed_models,
                f"{self.metadata_prefix}_native_deadline_at": (utcnow() + timedelta(hours=1)).isoformat(),
                "runtime_preparation": {
                    "phase": "files_verified",
                    "received_bytes": total,
                    "expected_bytes": total,
                    "verified_bytes": total,
                    "completed_files": len(inputs),
                    "file_count": len(inputs),
                },
            }
            session.commit()
            return False
        except Stopped:
            return True
        except DownloadBusy:
            try:
                DownloadExecutor.defer(session, run, worker=worker, claim=claim)
            except DownloadLostClaim:
                raise LostClaim() from None
            except Stopped:
                return True
            return "requeued"

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_speech_environment(
            run.id, {"profile": SPEECH_PROFILE, "permissions": PERMISSIONS}
        )

    def progress(self, run, value):
        key = self.metadata_prefix + "_preparation"
        if not isinstance(value, dict) or not isinstance(value.get(key), dict):
            return None
        incoming = value[key]
        phase = incoming.get("phase")
        if phase not in {
            "verifying_inputs",
            "creating_environment",
            "installing_dependencies",
            "building_sdk",
            "preparing_sdk",
            "checking_environment",
            "environment_prepared",
        }:
            return None
        return {
            **run.metadata_json.get("runtime_preparation", {}),
            "phase": phase,
            "sdk": incoming.get("sdk"),
            "native_completed_files": incoming.get("completed_files"),
            "native_file_count": incoming.get("file_count"),
            self.metadata_prefix + "_inference_tested": False,
        }

    def complete(self, session, run, result, runner):
        from app.artifacts import register_file
        from app.runs import transition
        from app.state import RunStatus

        if result.get("environment_prepared") is not True:
            raise ValueError(
                f"The completed native operation did not verify a {self.setup_label} environment"
            )
        entry = self.bundle(run.parameters["recipe"])
        root = get_settings().data_dir
        observed = run.metadata_json.get(self.metadata_prefix + "_model_observations") or {}
        files = publish_verified_models(
            session,
            entry,
            [
                (item, root / "models/store" / item.file.sha256, tuple(observed[item.file.sha256]))
                for item in entry.files
            ],
        )
        prepared = self.adopt(runner, run)
        if (
            prepared.get("profile") != run.parameters["profile"]
            or prepared.get("operation_id") != run.id
            or prepared.get("manifest_sha256") != run.parameters["manifest_sha256"]
            or prepared.get("environment_prepared") is not True
        ):
            raise ValueError(f"The native {self.setup_label} activation receipt changed")
        receipt = {**prepared, "model_files": files, self.metadata_prefix + "_inference_tested": False}
        with tempfile.NamedTemporaryFile("w", suffix=".json") as output:
            json.dump(receipt, output)
            output.flush()
            register_file(
                session,
                source=Path(output.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename=f"{self.setup_label}-runtime-preparation.json",
                run_id=run.id,
                metadata={"runtime_preparation": True, self.setup_label + "_setup": True},
            )
        total = sum(v["size_bytes"] for v in run.parameters["recipe"]["inputs"])
        run.metadata_json = {
            **run.metadata_json,
            "runtime_preparation": {
                "phase": "environment_prepared",
                "received_bytes": total,
                "expected_bytes": total,
                "model_file_ids": [v["model_file_id"] for v in files],
                self.metadata_prefix + "_inference_tested": False,
            },
        }
        run.summary = (
            "Speech runtime and model files prepared. Generate a first recording to check your voice."
            if self.setup_label == "speech"
            else f"{self.setup_label.capitalize()} runtime and model files prepared. Generate a first result to check the engine."
        )
        append_event(session, run.id, f"runtime.{self.metadata_prefix}.prepared", receipt)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
