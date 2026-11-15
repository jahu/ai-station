"""Fixed optional Live runtime setup over the private Runner transport."""

from app.runner_client import RunnerClient


class LiveSetupClient(RunnerClient):
    def runtime_setup_catalog(self):
        return self.request("GET", "/v1/setup/live")

    def prepare_runtime(self, payload):
        return self.request("POST", "/v1/setup/live/prepare", payload)

    def inspect_runtime_preparation(self, identity, *, stdout_offset=0, stderr_offset=0):
        return self.request(
            "GET", f"/v1/setup/live/{identity}?stdout_offset={stdout_offset}&stderr_offset={stderr_offset}"
        )

    def cancel_runtime_preparation(self, identity, payload):
        return self.request("POST", f"/v1/setup/live/{identity}/cancel", payload)

    def adopt_live_environment(self, identity, payload):
        return self.request("POST", f"/v1/setup/live/{identity}/adopt", payload)
