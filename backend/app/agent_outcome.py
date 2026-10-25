"""Project actual generation and delivery outcomes without rewriting Run history."""

from sqlalchemy import select

from app.agent_coding_policy import coding_provider
from app.models import Run, RunDependency

ACTIVE_ORDER = ("cancel_requested", "running", "preparing", "claimed", "waiting_for_approval", "queued")
BAD_ORDER = ("failed", "interrupted", "canceled")


def alert_check_runs(session, runs):
    """Classify checks and their model-only prerequisites, never data/code work."""
    by_id = {run.id: run for run in runs}
    checks = [
        run
        for run in runs
        if run.executor_type == "agent_result_alert"
        and (source := by_id.get(run.parameters.get("source_run_id"))) is not None
        and source.executor_type == "agent_data_result"
        and source.status == "succeeded"
        and run.parent_run_id == source.id
        and run.agent_id == source.agent_id
        and run.task_id == source.task_id
    ]
    selected = {run.id for run in checks}
    pending = list(selected)
    while pending:
        prerequisites = session.scalars(
            select(RunDependency.prerequisite_id).where(RunDependency.run_id.in_(pending))
        )
        following = []
        for key in prerequisites:
            source = by_id.get(key)
            if (
                source is not None
                and key not in selected
                and source.executor_type in {"llama_load", "llama_stop", "llama_resume_consumer"}
            ):
                selected.add(key)
                following.append(key)
        pending = following
    return [run for run in runs if run.id in selected]


def ranked_status(runs):
    for status in (*ACTIVE_ORDER, *BAD_ORDER):
        if any(run.status == status for run in runs):
            return status
    return "succeeded"


def superseded_failures(runs):
    by_id = {run.id: run for run in runs}
    ignored = set()
    for source in runs:
        repair = by_id.get(source.metadata_json.get("repair_run_id"))
        if repair is None or repair.task_id != source.task_id or repair.agent_id != source.agent_id:
            continue
        if (
            source.executor_type == "project_validation"
            and source.status == "failed"
            and source.error_type == "ValidationFailed"
            and repair.executor_type == "local_proposal"
            and repair.parent_run_id == source.id
            and repair.parameters.get("repair_validation_run_id") == source.id
        ):
            original = by_id.get(repair.parameters.get("repair_source_run_id"))
            if (
                original
                and original.executor_type == "local_proposal"
                and original.status == "succeeded"
                and original.metadata_json.get("validation_run_id") == source.id
                and source.parent_run_id == original.id
                and original.project_id == source.project_id == repair.project_id
                and original.metadata_json.get("repair_run_id") == repair.id
            ):
                ignored.add(source.id)
        if (
            source.executor_type == "agent_data_result"
            and source.status == "succeeded"
            and repair.executor_type == "agent_data_generate"
            and repair.parent_run_id == source.id
            and repair.parameters.get("repair")
        ):
            old = source.parameters.get("agent_data") or {}
            new = repair.parameters.get("agent_data") or {}
            if isinstance(old.get("attempt"), int) and new == {**old, "attempt": old["attempt"] + 1}:
                python = by_id.get(source.parameters.get("python_run_id"))
                if (
                    python
                    and source.parent_run_id == python.id
                    and python.executor_type == "python"
                    and python.status == "failed"
                    and python.error_type == "PythonProgramFailed"
                    and python.metadata_json.get("process_confirmed_gone")
                    and python.metadata_json.get("data_result_run_id") == source.id
                    and python.parameters.get("agent_data") == old
                    and python.project_id == source.project_id == repair.project_id
                ):
                    ignored.add(python.id)
    return ignored


def final_runs(root, runs):
    definition = root.parameters.get("definition") or {}
    tools = definition.get("tools", [])
    media = definition.get("media")
    if media:
        expected = {
            "image": "photo_pipe",
            "music": "ace_step_music",
            "speech": "chatterbox",
            "video": "media_compose",
            "avatar": "media_compose",
        }.get(media.get("kind"))
        return [
            run
            for run in runs
            if run.executor_type == expected and not run.metadata_json.get("upscale_run_id")
        ]
    if "python_data" in tools:
        return [
            run
            for run in runs
            if run.executor_type == "agent_data_result" and not run.metadata_json.get("repair_run_id")
        ]
    provider = coding_provider(tools)
    if provider:
        return [
            run
            for run in runs
            if (
                run.executor_type == "project_validation"
                or run.executor_type == f"{provider}_proposal"
                and not run.parameters.get("commands")
            )
            and not run.metadata_json.get("repair_run_id")
        ]
    if tools == ["market_watch"]:
        return [
            run
            for run in runs
            if run.executor_type == "agent_market" and run.parameters.get("tool") == "market.report"
        ]
    return [run for run in runs if run.executor_type == "agent" and run.parent_run_id == root.id]


def workflow_outcome(session, root):
    runs = list(
        session.scalars(select(Run).where(Run.task_id == root.task_id).order_by(Run.created_at, Run.id))
    )
    owned = [run for run in runs if run.agent_id == root.agent_id]
    # Email is a separate typed workload. Its approval/transport cannot turn a
    # completed report into an unfinished generation or erase its saved result.
    delivery = [run for run in owned if run.executor_type == "email_send"]
    checks = alert_check_runs(session, owned)
    check_ids = {run.id for run in checks}
    generation = [run for run in owned if run.executor_type != "email_send" and run.id not in check_ids]
    ignored = superseded_failures(generation)
    relevant = [run for run in generation if run.id not in ignored]
    status = ranked_status(relevant)
    final = final_runs(root, generation)
    if status == "succeeded" and (not final or any(run.status != "succeeded" for run in final)):
        status = "interrupted"
    if (
        root.task.metadata_json.get("stop_requested_at")
        and status == "succeeded"
        and not delivery
        and not checks
    ):
        status = "canceled"
    value = {"status": status}
    if checks:
        value.update(alert_status=ranked_status(checks), alert_run_id=checks[-1].id)
    if len(final) == 1:
        value["result_run_id"] = final[0].id
    if delivery:
        value.update(delivery_status=ranked_status(delivery), delivery_run_id=delivery[-1].id)
    elif any(
        (run.metadata_json.get("result_email") or {}).get("state") == "preparation_failed"
        for run in generation
    ):
        value["delivery_status"] = "failed"
    return value
