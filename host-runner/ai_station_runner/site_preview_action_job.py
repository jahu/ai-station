"""Managed per-action proxy; uncertain or interrupted sends are never repeated."""

import sys
import time
from uuid import UUID

from ai_station_runner.site_preview_job import ensure_registered
from ai_station_runner.site_preview_runs import (
    PreviewAction,
    action_result,
    cancel_action,
    load_request,
    locked,
    path,
    read,
    save,
)


def execute(run_id):
    ensure_registered(run_id, "site_preview_action")
    saved = load_request(run_id, action=True)
    body = PreviewAction.model_validate(saved["request"])
    preview_id = str(body.preview_run_id)
    try:
        with locked(path(run_id, "action.lock", action=True)):
            if action_result(run_id)["state"] == "canceled":
                return
            if action_result(run_id)["state"] != "pending":
                raise ValueError("Uncertain preview action dispatch is never replayed")
            if path(preview_id, "cancel.json").exists():
                raise ValueError("Preview closed before interaction")
            save(path(preview_id, f"queue/{run_id}.json"), {"run_id": run_id})
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            result = action_result(run_id)
            if result["state"] in {"frame", "rejected", "canceled"}:
                return
            if path(preview_id, "cancel.json").exists():
                raise ValueError("Preview closed during interaction")
            manifest = path(preview_id, "container.json")
            if manifest.exists() and read(manifest).get("state") == "removed":
                raise ValueError("Preview ended during interaction")
            time.sleep(0.05)
        raise ValueError("Preview interaction exceeded its deadline")
    finally:
        if not cancel_action(run_id):
            raise ValueError("Interaction cleanup requires inspection")


if __name__ == "__main__":
    try:
        execute(str(UUID(sys.argv[1])))
    except Exception as exc:
        print(
            "Preview interaction stopped: "
            + type(exc).__name__
            + (": " + str(exc) if type(exc) is ValueError else ""),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
