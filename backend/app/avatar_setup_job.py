"""Avatar inputs/activation reuse verified downloads and the owned setup worker."""

from app.avatar_setup_client import AvatarSetupClient
from app.model_bundles import Bundle, BundleFile
from app.runtime_setup_api import AVATAR_PROFILE, PERMISSIONS
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec


def model_bundle(recipe):
    repository, revision = recipe["model_repository"], recipe["model_revision"]
    return Bundle(
        id="sonic-whole-weights-v1",
        name="Sonic · whole-recording avatar companions",
        capability="avatar",
        family="sonic",
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


class AvatarSetupExecutor(SpeechSetupExecutor):
    name = "avatar_setup"
    storage_headroom_bytes = 12 * 1024**3
    metadata_prefix = "avatar"
    setup_label = "avatar"

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") != AVATAR_PROFILE
            or not 1 <= len(inputs) <= 192
            or len({v["sha256"] for v in inputs}) != len(inputs)
            or {v.get("kind") for v in inputs} != {"python", "sdk", "wheel", "sdist", "model"}
            or len([v for v in inputs if v["kind"] == "model"]) != 14
        ):
            raise ValueError("Avatar setup requires its complete reviewed source and companion manifest")
        model_bundle(recipe)

    def runner(self):
        return AvatarSetupClient(timeout=30)

    def payload(self, run):
        return dict(
            run_id=run.id,
            profile=AVATAR_PROFILE,
            manifest_sha256=run.parameters["manifest_sha256"],
            deadline_at=run.metadata_json["avatar_native_deadline_at"],
            permissions=PERMISSIONS,
        )

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_avatar_environment(
            run.id, {"profile": AVATAR_PROFILE, "permissions": PERMISSIONS}
        )
