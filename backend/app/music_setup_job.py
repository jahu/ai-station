"""Music inputs/activation reuse verified downloads and the owned setup worker."""

from app.model_bundles import Bundle, BundleFile
from app.music_setup_client import MusicSetupClient
from app.runtime_setup_api import MUSIC_PROFILE, PERMISSIONS
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec


def model_bundle(recipe):
    repository, revision = recipe["model_repository"], recipe["model_revision"]
    return Bundle(
        id="ace-step15-turbo-no-lm-weights-v1",
        name="ACE-Step 1.5 Turbo · music model companions",
        capability="music",
        family="ace_step15",
        license="MIT",
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


class MusicSetupExecutor(SpeechSetupExecutor):
    name = "music_setup"
    metadata_prefix = "music"
    setup_label = "music"

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") != MUSIC_PROFILE
            or not 1 <= len(inputs) <= 192
            or len({v["sha256"] for v in inputs}) != len(inputs)
            or {v.get("kind") for v in inputs} != {"python", "sdk", "wheel", "model"}
            or len([v for v in inputs if v["kind"] == "model"]) != 16
        ):
            raise ValueError("Music setup requires its complete reviewed source and companion manifest")
        model_bundle(recipe)

    def runner(self):
        return MusicSetupClient(timeout=30)

    def payload(self, run):
        return dict(
            run_id=run.id,
            profile=MUSIC_PROFILE,
            manifest_sha256=run.parameters["manifest_sha256"],
            deadline_at=run.metadata_json["music_native_deadline_at"],
            permissions=PERMISSIONS,
        )

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_music_environment(run.id, {"profile": MUSIC_PROFILE, "permissions": PERMISSIONS})
