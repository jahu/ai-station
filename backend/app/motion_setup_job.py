"""Existing owned runtime setup lifecycle; native activation never loads an AI model."""

from app.motion_setup_client import PROFILE, MotionSetupClient
from app.runtime_setup_job import RuntimeSetupExecutor, publish_image_receipt


class MotionSetupExecutor(RuntimeSetupExecutor):
    name = "motion_setup"

    def runner(self):
        return MotionSetupClient(timeout=30)

    def validate(self, run):
        super().validate(run)
        if (
            run.parameters.get("profile") != PROFILE
            or run.parameters["recipe"].get("preparation_mode") != "existing_image"
        ):
            raise ValueError("Use the fixed reviewed local renderer activation")

    def complete(self, session, run, result, runner):
        observed = runner.runtime_setup_catalog()
        if (
            observed.get("manifest_sha256") != run.parameters["manifest_sha256"]
            or observed.get("usable_image") is not True
            or not result.get("renderer_observation")
            or result["renderer_observation"] != observed.get("renderer_observation")
            or result.get("image") != observed.get("selected_image")
        ):
            raise ValueError("The selected native renderer changed before publication")
        publish_image_receipt(session, run, result)
        run.summary = "Local Full-HD film export is ready."
        run.metadata_json = {**run.metadata_json, "renderer_observation": result["renderer_observation"]}
        return "done"
