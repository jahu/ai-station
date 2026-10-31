"""Fixed image lifecycle transport; explicit Stop also fences an unseen dispatch."""

from app.runner_client import RunnerClient


class ManagedImageClient(RunnerClient):
    def inspect_process(self, run_id, *, stdout_offset=0, stderr_offset=0):
        return self.request(
            "GET",
            f"/v1/images/jobs/{run_id}?stdout_offset={stdout_offset or 0}&stderr_offset={stderr_offset or 0}",
        )

    def cancel_process(self, run_id):
        return self.request(
            "POST",
            f"/v1/images/jobs/{run_id}/cancel",
            {"permissions": ["filesystem_read", "workspace_write"]},
        )


def fence_missing_dispatch(runner, run):
    info = runner.request(
        "POST",
        f"/v1/images/jobs/{run.id}/cancel",
        {"permissions": ["filesystem_read", "workspace_write"]},
    )
    if (
        info.get("run_id") != run.id
        or info.get("executor") != "photo_pipe"
        or info.get("execution_target") != "container"
        or info.get("alive") is not False
        or info.get("completion_pending")
        or info.get("status") != "canceled"
    ):
        raise ValueError("The delayed image dispatch has not been safely fenced")
    return info
