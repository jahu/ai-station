"""Native SDK downloads/activation reuse the ordinary owned setup worker."""

import json
import tempfile
from pathlib import Path

from app.artifacts import register_file
from app.events import append_event
from app.native_llama_setup_client import NativeLlamaSetupClient
from app.runs import transition
from app.runtime_setup_api import NATIVE_LLAMA_PROFILES, PERMISSIONS
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec
from app.state import RunStatus


class NativeLlamaSetupExecutor(SpeechSetupExecutor):
    name = "native_llama_setup"
    ram_mib = 1024
    metadata_prefix = "native_llama"
    setup_label = "native llama.cpp SDK"
    storage_headroom_bytes = 256 * 1024**2

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") not in NATIVE_LLAMA_PROFILES
            or recipe.get("platform") not in {"darwin/arm64", "darwin/x86_64"}
            or recipe.get("release") != "b12032"
            or len(inputs) != 1
            or inputs[0].get("kind") != "native_engine"
            or not 0 < inputs[0].get("size_bytes", 0) <= 256 * 1024**2
        ):
            raise ValueError("Native SDK setup requires its fixed reviewed architecture and engine archive")
        file_spec(inputs[0])

    def runner(self):
        return NativeLlamaSetupClient(timeout=30)

    def payload(self, run):
        return {
            "run_id": run.id,
            "profile": run.parameters["profile"],
            "manifest_sha256": run.parameters["manifest_sha256"],
            "deadline_at": run.metadata_json["native_llama_native_deadline_at"],
            "permissions": PERMISSIONS,
        }

    def complete(self, session, run, result, runner):
        if result.get("environment_prepared") is not True:
            raise ValueError("The native SDK operation did not verify its environment")
        prepared = runner.adopt_native_llama_environment(
            run.id, {"profile": run.parameters["profile"], "permissions": PERMISSIONS}
        )
        from app.model_setup import fingerprint

        observed = {
            "profile": run.parameters["profile"],
            "operation_id": run.id,
            "manifest_sha256": run.parameters["manifest_sha256"],
        }
        if (
            any(prepared.get(key) != value for key, value in observed.items())
            or prepared.get("environment_id") != fingerprint(observed)
            or prepared.get("environment_prepared") is not True
            or prepared.get("sdk_prepared") is not True
        ):
            raise ValueError("The native SDK activation receipt changed")
        receipt = {**prepared, "model_inference_tested": False}
        with tempfile.NamedTemporaryFile("w", suffix=".json") as output:
            json.dump(receipt, output)
            output.flush()
            register_file(
                session,
                source=Path(output.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="native-llama-runtime-preparation.json",
                run_id=run.id,
                metadata={"runtime_preparation": True, "native_llama_setup": True},
            )
        total = sum(item["size_bytes"] for item in run.parameters["recipe"]["inputs"])
        run.metadata_json = {
            **run.metadata_json,
            "runtime_preparation": {
                "phase": "environment_prepared",
                "received_bytes": total,
                "expected_bytes": total,
                "environment_id": prepared["environment_id"],
                "model_inference_tested": False,
            },
        }
        run.summary = (
            "Native llama.cpp SDK prepared. Model loading and first inference are checked separately."
        )
        append_event(session, run.id, "runtime.native_llama.prepared", receipt)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
