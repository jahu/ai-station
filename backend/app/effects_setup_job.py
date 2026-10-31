"""Effects inputs/activation reuse verified downloads and the owned setup worker."""

from app.effects_setup_client import EffectsSetupClient
from app.model_bundles import Bundle, BundleFile
from app.runtime_setup_api import EFFECTS_PROFILE, PERMISSIONS
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec


def model_bundle(recipe):
    repository, revision = recipe["model_repository"], recipe["model_revision"]
    return Bundle(
        id="mmaudio-large44-weights-v1",
        name="MMAudio · film sound companions",
        capability="effects",
        family="mmaudio",
        license="Multiple component licenses",
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


class EffectsSetupExecutor(SpeechSetupExecutor):
    name = "effects_setup"
    storage_headroom_bytes = 12 * 1024**3
    metadata_prefix = "effects"
    setup_label = "effects"

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") != EFFECTS_PROFILE
            or not 1 <= len(inputs) <= 192
            or len({v["sha256"] for v in inputs}) != len(inputs)
            or {v.get("kind") for v in inputs} != {"python", "sdk", "wheel", "sdist", "model"}
            or len([v for v in inputs if v["kind"] == "model"]) != 7
        ):
            raise ValueError("Effects setup requires its complete reviewed source and companion manifest")
        model_bundle(recipe)

    def runner(self):
        return EffectsSetupClient(timeout=30)

    def payload(self, run):
        return dict(
            run_id=run.id,
            profile=EFFECTS_PROFILE,
            manifest_sha256=run.parameters["manifest_sha256"],
            deadline_at=run.metadata_json["effects_native_deadline_at"],
            permissions=PERMISSIONS,
        )

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_effects_environment(
            run.id, {"profile": EFFECTS_PROFILE, "permissions": PERMISSIONS}
        )
