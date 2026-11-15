"""Live sessions use ordinary Run claims, resource locks and owned-process recovery."""

import json

from app.host_media_executor import HostMediaExecutor
from app.permissions import require
from app.resources import release_run_locks, reserve_gpu_bundle
from app.runner_client import RunnerClient, RunnerError
from app.runs import transition
from app.state import RunStatus

NAME = "live_identity"
RAM_MIB = 12288


class LiveRunnerClient(RunnerClient):
    def cancel_process(self, run_id):
        result = self.request("POST", f"/v1/live/{run_id}/cancel")
        if (
            result.get("run_id") != str(run_id)
            or result.get("executor") != NAME
            or type(result.get("alive")) is not bool
        ):
            raise RunnerError(502, "The native Live cancellation identity changed")
        return result


class LiveExecutor(HostMediaExecutor):
    name = NAME
    suffix = ".json"
    artifact_type = "json"
    mime_type = "application/json"

    def runner(self, run):
        return LiveRunnerClient()

    def reserve_devices_from_hardware(self, session, run, hardware):
        eligible = run.parameters["eligible_gpu_indices"]
        indexes = [
            int(g["index"])
            for g in hardware.get("gpus", [])
            if int(g["index"]) in eligible and (g.get("memory_total_mib") or 0) >= 4096
        ]
        count = int(run.parameters.get("image") is not None) + int(run.parameters.get("voice") is not None)
        free = [
            int(g["index"])
            for g in hardware.get("gpus", [])
            if int(g["index"]) in indexes
            and (g.get("memory_total_mib", 0) - g.get("memory_used_mib", 0)) >= 3072
        ]
        if len(indexes) >= count and len(free) < count:
            return None
        return reserve_gpu_bundle(session, run, free, count)

    def validate_inputs(self, session, run):
        from app.live import reference

        for medium in ("image", "voice"):
            if run.parameters.get(medium) is not None:
                if (
                    reference(session, run.parameters[medium + "_artifact_id"], medium, run.owner_id)
                    != run.parameters[medium]
                ):
                    raise ValueError("The frozen Live reference was removed or changed")

    def _start(self, runner, run, allocated, output):
        for name in ("filesystem_read", "workspace_write"):
            require(run.effective_permissions, name)
        if run.requested_resources.get("ram_mib") != RAM_MIB:
            raise ValueError("Live requires its complete fixed RAM reservation")
        return runner.request(
            "POST",
            "/v1/runs/live",
            {
                "run_id": run.id,
                **({"mode": run.parameters["mode"]} if "mode" in run.parameters else {}),
                "managed_runtime": run.parameters["managed_runtime"],
                "image": run.parameters.get("image"),
                "voice": run.parameters.get("voice"),
                "gpus": [int(gpu) for gpu in run.allocated_resources["gpus"]],
                "ram_mib": RAM_MIB,
                "seed": run.parameters["seed"],
                "permissions": ["filesystem_read", "workspace_write"],
                **self.native_budget(run),
            },
        )

    def fence_missing_dispatch(self, runner, run):
        runner.cancel_process(run.id)

    def on_inspection(self, session, run, info):
        for line in info.get("stdout", "").splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get("live_ready") is True:
                run.metadata_json = {**run.metadata_json, "live_ready": True}
            if isinstance(value.get("live_statistics"), dict):
                run.metadata_json = {**run.metadata_json, "live_statistics": value["live_statistics"]}
            if isinstance(value.get("live_failure"), dict) and isinstance(
                value["live_failure"].get("reason"), str
            ):
                from app.events import append_event

                reason = value["live_failure"]["reason"][:80]
                if run.metadata_json.get("live_failure") != reason:
                    append_event(session, run.id, "live.stream.failed", {"reason": reason})
                run.metadata_json = {**run.metadata_json, "live_failure": reason}
        if (
            not info.get("alive")
            and not info.get("completion_pending")
            and info.get("exit_code") == 75
            and run.status != "cancel_requested"
        ):
            release_run_locks(session, run.id)
            run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True, "live_ready": False}
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Live connection closed; start a new session to resume capture"},
            )
