"""Video inputs/activation reuse verified downloads and the owned setup worker."""

from app.model_bundles import Bundle, BundleFile
from app.runtime_setup_api import PERMISSIONS, VIDEO_PROFILE
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec
from app.video_setup_client import VideoSetupClient


def model_bundle(recipe):
    repository, revision = recipe["model_repository"], recipe["model_revision"]
    return Bundle(
        id="wan22-5b-weights-v1",
        name="Wan 2.2 5B · video model companions",
        capability="video",
        family="wan22",
        license="Apache-2.0",
        license_url=recipe["model_license_url"],
        source_url=f"https://huggingface.co/{repository}/tree/{revision}",
        repository=repository,
        revision=revision,
        files=tuple(
            BundleFile(filename=v["filename"].replace("/", "--"), file=file_spec(v))
            for v in recipe["inputs"]
            if v["kind"] == "model"
        ),
    )


class VideoSetupExecutor(SpeechSetupExecutor):
    name = "video_setup"
    storage_headroom_bytes = 12 * 1024**3
    metadata_prefix = "video"
    setup_label = "video"

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") != VIDEO_PROFILE
            or not 1 <= len(inputs) <= 192
            or len({v["sha256"] for v in inputs}) != len(inputs)
            or {v.get("kind") for v in inputs} != {"python", "sdk", "wheel", "model"}
            or len([v for v in inputs if v["kind"] == "model"]) != 3
        ):
            raise ValueError("Video setup requires its complete reviewed source and companion manifest")
        model_bundle(recipe)

    def runner(self):
        return VideoSetupClient(timeout=30)

    def payload(self, run):
        return dict(
            run_id=run.id,
            profile=VIDEO_PROFILE,
            manifest_sha256=run.parameters["manifest_sha256"],
            deadline_at=run.metadata_json["video_native_deadline_at"],
            permissions=PERMISSIONS,
        )

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_video_environment(run.id, {"profile": VIDEO_PROFILE, "permissions": PERMISSIONS})
