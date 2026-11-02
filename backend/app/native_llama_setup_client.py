"""Typed native SDK preparation over the existing private Runner connection."""

from app.runner_client import RunnerClient


class NativeLlamaSetupClient(RunnerClient):
    def runtime_setup_catalog(self, *, profile):
        return self.request("GET", "/v1/setup/native-llama?profile=" + profile)

    def prepare_runtime(self, payload):
        return self.request("POST", "/v1/setup/native-llama/prepare", payload)

    def inspect_runtime_preparation(self, identity, *, stdout_offset=0, stderr_offset=0):
        return self.request(
            "GET",
            f"/v1/setup/native-llama/{identity}?stdout_offset={stdout_offset}&stderr_offset={stderr_offset}",
        )

    def cancel_runtime_preparation(self, identity, payload):
        return self.request("POST", f"/v1/setup/native-llama/{identity}/cancel", payload)

    def adopt_native_llama_environment(self, identity, payload):
        return self.request("POST", f"/v1/setup/native-llama/{identity}/adopt", payload)
