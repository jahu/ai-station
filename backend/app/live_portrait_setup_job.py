"""The portrait addon reuses Live's durable download, preparation and adoption flow."""

from app.live_setup_client import PortraitSetupClient
from app.live_setup_job import LiveSetupExecutor
from app.model_bundles import Bundle, BundleFile
from app.speech_setup_job import file_spec

MANIFEST = "a0b635338ffa58f3318318326e8df4c2794cfcf1fcd6f169c41ac08b4ac92678"
PROFILE = "live-portrait-linux-x86-64-python312-v1"


class PortraitSetupExecutor(LiveSetupExecutor):
    name = "live_portrait_setup"
    profile = PROFILE
    manifest = MANIFEST
    metadata_prefix = setup_label = "live_portrait"
    storage_headroom_bytes = 128 * 1024**2

    def runner(self):
        return PortraitSetupClient(timeout=30)

    def bundle(self, recipe):
        return Bundle(
            id="live-portrait-human-v1",
            name="LivePortrait · human portrait animation",
            capability="live",
            family="live_portrait",
            license="MIT",
            license_url=recipe["source_license_url"],
            source_url=recipe["model_license_url"],
            repository="KlingTeam/LivePortrait",
            revision=recipe["model_revision"],
            files=tuple(
                BundleFile(filename=v["filename"], file=file_spec(v))
                for v in recipe["inputs"]
                if v["kind"] == "model"
            ),
        )
