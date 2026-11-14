"""Video inputs/activation reuse verified downloads and the owned setup worker."""

from app.model_bundles import Bundle, BundleFile
from app.runtime_setup_api import PERMISSIONS, SVI_PROFILE
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec
from app.svi_setup_client import SviSetupClient


def model_bundle(recipe):
    repository, revision = recipe["model_repository"], recipe["model_revision"]
    return Bundle(
        id="wan22-svi-pro-q4-weights-v1",
        name="Wan 2.2 SVI Pro Q4 · complete model components",
        capability="video",
        family="wan22",
        license=recipe["model_license"],
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


class SviSetupExecutor(SpeechSetupExecutor):
    name = "svi_setup"
    storage_headroom_bytes = 12 * 1024**3
    metadata_prefix = "svi"
    setup_label = "svi"

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        recipe = run.parameters["recipe"]
        inputs = recipe.get("inputs") or []
        if (
            run.parameters.get("profile") != SVI_PROFILE
            or not 1 <= len(inputs) <= 192
            or len({v["sha256"] for v in inputs}) != len(inputs)
            or {v.get("kind") for v in inputs} != {"python", "sdk", "wheel", "model"}
            or len([v for v in inputs if v["kind"] == "model"]) != 6
        ):
            raise ValueError("Video setup requires its complete reviewed source and companion manifest")
        roles = [v.get("role") for v in inputs if v["kind"] == "model"]
        if set(roles) != {
            "wan_high_noise",
            "wan_low_noise",
            "svi_high_adapter",
            "svi_low_adapter",
            "wan_text_encoder",
            "wan_vae",
        }:
            raise ValueError("SVI setup requires exactly its six named model components")
        model_bundle(recipe)

    def runner(self):
        return SviSetupClient(timeout=30)

    def payload(self, run):
        return dict(
            run_id=run.id,
            profile=SVI_PROFILE,
            manifest_sha256=run.parameters["manifest_sha256"],
            deadline_at=run.metadata_json["svi_native_deadline_at"],
            permissions=PERMISSIONS,
        )

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_svi_environment(run.id, {"profile": SVI_PROFILE, "permissions": PERMISSIONS})
