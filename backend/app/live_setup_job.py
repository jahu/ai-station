"""Live reuses the verified-download and owned offline setup lifecycle."""

from app.live_setup_client import LiveSetupClient
from app.model_bundles import Bundle, BundleFile
from app.runtime_setup_api import LIVE_PROFILE, PERMISSIONS
from app.runtime_setup_job import RuntimeSetupExecutor
from app.speech_setup_job import SpeechSetupExecutor, file_spec

MANIFEST = "4efdf390b80da847e8c1e89861de73241e1d9fda267e04e027bd0021cdca82ba"


def model_bundle(recipe):
    return Bundle(
        id="live-identity-components-v1",
        name="Live · face and voice components",
        capability="live",
        family="live_identity",
        license="Multiple component licenses",
        license_url=recipe["model_license_url"],
        source_url="https://github.com/jahu/ai-station/blob/"
        + recipe["bridge_revision"]
        + "/docs/plans/live-identity.md",
        repository="jahu/ai-station",
        revision=recipe["bridge_revision"],
        files=tuple(
            BundleFile(filename=v["filename"], file=file_spec(v))
            for v in recipe["inputs"]
            if v["kind"] == "model"
        ),
    )


class LiveSetupExecutor(SpeechSetupExecutor):
    name = "live_setup"
    metadata_prefix = setup_label = "live"
    storage_headroom_bytes = 9 * 1024**3

    def validate(self, run):
        RuntimeSetupExecutor.validate(self, run)
        if run.parameters.get("profile") != LIVE_PROFILE or run.parameters.get("manifest_sha256") != MANIFEST:
            raise ValueError("Live requires its exact reviewed engine and model recipe")
        model_bundle(run.parameters["recipe"])

    def runner(self):
        return LiveSetupClient(timeout=30)

    def payload(self, run):
        return dict(
            run_id=run.id,
            profile=LIVE_PROFILE,
            manifest_sha256=MANIFEST,
            deadline_at=run.metadata_json["live_native_deadline_at"],
            permissions=PERMISSIONS,
        )

    def bundle(self, recipe):
        return model_bundle(recipe)

    def adopt(self, runner, run):
        return runner.adopt_live_environment(run.id, {"profile": LIVE_PROFILE, "permissions": PERMISSIONS})
