"""Only fixed Studio renderer preparation endpoints on the private Runner."""

from app.runner_client import RunnerClient

PROFILE = "hyperframes-cpu-linux-amd64-v1"


class MotionSetupClient(RunnerClient):
    def runtime_setup_catalog(self):
        return self.request("GET", "/v1/setup/motion")

    def prepare_runtime(self, payload):
        return self.request("POST", "/v1/setup/motion/prepare", payload)

    def inspect_runtime_preparation(self, identity, *, stdout_offset=0, stderr_offset=0):
        return self.request(
            "GET", f"/v1/setup/motion/{identity}?stdout_offset={stdout_offset}&stderr_offset={stderr_offset}"
        )

    def cancel_runtime_preparation(self, identity, payload):
        return self.request("POST", f"/v1/setup/motion/{identity}/cancel", payload)
