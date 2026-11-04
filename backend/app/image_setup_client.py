"""Fixed image catalog plus the existing typed native OCI preparation transport."""

from app.runner_client import RunnerClient


class ImageSetupClient(RunnerClient):
    def runtime_setup_catalog(self):
        return self.request("GET", "/v1/setup/images")
