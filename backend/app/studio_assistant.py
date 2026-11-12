"""One durable conversation tool composes the existing Studio production services.

Its model supplies editorial text and captured aliases, never task IDs or paths.
Waiting relinquishes the worker; only the complete owned MP4 fulfills the tool.
"""

from datetime import datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import select

from app.models import Artifact, Run, StudioRevision
from app.permissions import require
from app.runs import transition
from app.state import TERMINAL, RunStatus
from app.studio_assistant_contract import StudioCall, StudioIntent, reference_ids, selected_context

NAME = "assistant_studio"
PERMISSIONS = ("filesystem_read", "workspace_write")


def request_parameters(session, root, raw):
    from app.assistant_controller import missing_outcomes
    from app.assistant_controller_tools import catalog

    args = StudioCall.model_validate(raw)
    outcomes = root.metadata_json.get("controller_outcomes", [])
    candidates = [i for i, o in enumerate(outcomes) if o["kind"] == "studio_material"]
    index = args.outcome_index
    if index is None:
        if len(candidates) != 1:
            raise ValueError("Choose the original Studio outcome_index")
        index = candidates[0]
    if index not in candidates:
        raise ValueError("Choose a requested Studio material outcome")
    outcome = outcomes[index]
    observations = [
        s["observation"] for s in root.metadata_json.get("controller_steps", []) if s.get("observation")
    ]
    from app.studio_assistant_contract import exhausted_studio_outcomes

    if index in exhausted_studio_outcomes(observations):
        raise ValueError(
            "This Studio outcome exhausted its bounded planning corrections. Preserve the failed draft and explain the actual failure; a new instruction may revise it. Do not recreate the whole workflow with a paraphrase."
        )
    if not any(p.get("outcome_index") == index for p in missing_outcomes(observations, outcomes)):
        raise ValueError("This Studio outcome is already fulfilled")
    if root.parameters["controller_provider"].get("location") != "local":
        raise ValueError("Studio direction requires the selected local model")
    chosen = selected_context(
        session,
        root.parameters.get("controller_creative_projects", {}),
        StudioIntent.model_validate(outcome["studio"]),
    )
    entries = catalog(session, root)
    required = [
        a for a in outcome.get("source_inputs", []) if entries.get(a, {}).get("type") in {"image", "video"}
    ]
    supplied = set(args.references) | ({args.presenter_reference} if args.presenter_reference else set())
    if not set(required).issubset(supplied):
        raise ValueError("Preserve the requested supplied Studio media references")
    references = reference_ids(session, owner_id=root.owner_id, entries=entries, aliases=args.references)
    presenter = None
    if args.presenter_reference:
        if entries.get(args.presenter_reference, {}).get("type") != "image":
            raise ValueError("Choose a supplied image alias for the presenter")
        image = reference_ids(
            session, owner_id=root.owner_id, entries=entries, aliases=[args.presenter_reference]
        )[0]
        presenter = {"image_artifact_id": image, "placement": args.presenter_placement or "auto"}
    return {
        "controller_parent_id": root.id,
        "instruction": args.instruction,
        "title": args.title,
        "outcome_index": index,
        "reference_artifact_ids": references,
        **({"presenter": presenter} if presenter else {}),
        **chosen,
        "model": root.parameters["controller_request"]["model"],
        "execution_deadline_at": root.parameters["execution_deadline_at"],
    }


def child_tasks(session, wrapper):
    """Closed two-stage receipt, also used by Stop; no model-chosen traversal."""
    receipts = wrapper.metadata_json.get("studio_assistant_children", [])
    if [r["kind"] for r in receipts] not in ([], ["plan"], ["plan", "production"]):
        raise ValueError("Studio assistant child registry changed")
    result = []
    for receipt in receipts:
        primary = session.get(Run, receipt["run_id"])
        expected = {"plan": "studio_director", "production": "studio_production_step"}.get(receipt["kind"])
        if not (
            expected
            and primary
            and primary.executor_type == expected
            and primary.parent_run_id == wrapper.id
            and primary.task_id == receipt["task_id"]
            and primary.task_id != wrapper.task_id
            and primary.owner_id == wrapper.owner_id
            and primary.parameters.get("studio_material_id")
            == wrapper.metadata_json.get("studio_material_id")
            and primary.conversation_id == wrapper.conversation_id
            and primary.task.conversation_id == wrapper.conversation_id
            and primary.task.owner_id == wrapper.owner_id
            and primary.task.metadata_json.get("studio_assistant_parent_id") == wrapper.id
        ):
            raise ValueError("Studio assistant child ownership changed")
        if receipt["kind"] == "production":
            from app.studio_production import root_run

            root_run(session, primary.id, wrapper.metadata_json.get("studio_material_id"))
        result.append((receipt["kind"], primary))
    return result


def attach(session, wrapper, primary, kind):
    if any(k == kind for k, _ in child_tasks(session, wrapper)):
        raise ValueError("Studio assistant stage already published")
    if primary.owner_id != wrapper.owner_id or primary.task_id == wrapper.task_id:
        raise ValueError("Studio assistant requires a separate owned Task")
    primary.parent_run_id = wrapper.id
    primary.task.conversation_id = wrapper.conversation_id
    primary.task.metadata_json = {**primary.task.metadata_json, "studio_assistant_parent_id": wrapper.id}
    for child in session.scalars(select(Run).where(Run.task_id == primary.task_id)):
        child.conversation_id = wrapper.conversation_id
        deadline = min(
            datetime.fromisoformat(
                child.parameters.get("execution_deadline_at", wrapper.parameters["execution_deadline_at"])
            ),
            datetime.fromisoformat(wrapper.parameters["execution_deadline_at"]),
        )
        child.parameters = {**child.parameters, "execution_deadline_at": deadline.isoformat()}
    wrapper.metadata_json = {
        **wrapper.metadata_json,
        "studio_assistant_children": [
            *wrapper.metadata_json.get("studio_assistant_children", []),
            {"kind": kind, "task_id": primary.task_id, "run_id": primary.id},
        ],
    }


def stage_runs(session, kind, primary):
    if kind == "production":
        from app.studio_production import all_runs

        return all_runs(session, primary)
    return list(session.scalars(select(Run).where(Run.task_id == primary.task_id)))


def final_output(session, wrapper):
    """Only a completed verified renderer from this full production is publishable."""
    from app.assistant_controller import verify_wrapper
    from app.studio_production import children, complete_media

    verify_wrapper(session, wrapper)
    production = next((p for k, p in child_tasks(session, wrapper) if k == "production"), None)
    if production is None:
        return None
    rows = stage_runs(session, "production", production)
    if any(r.status != "succeeded" for r in rows):
        return None
    render = session.get(Run, production.metadata_json.get("render_run_id", ""))
    owned = {t.id for t in children(session, production)}
    if not render or render.executor_type != "motion_render" or render.task_id not in owned:
        return None
    outputs = list(
        session.scalars(
            select(Artifact).where(
                Artifact.run_id == render.id,
                Artifact.artifact_type == "video",
                Artifact.mime_type == "video/mp4",
                Artifact.trashed_at.is_(None),
                Artifact.purged_at.is_(None),
                Artifact.purge_run_id.is_(None),
            )
        )
    )
    if not outputs:
        return None  # Historical conversation remains readable after Library Trash/purge.
    if len(outputs) != 1:
        raise ValueError("A complete Studio export must have one final MP4")
    output = outputs[0]
    if output.owner_id != wrapper.owner_id:
        raise ValueError("Studio final output owner changed")
    complete_media(session, output.id, "video")
    return output


class AssistantStudioExecutor:
    name = NAME

    def execute(self, session, run):
        from app.assistant_controller import verify_wrapper, wait_for
        from app.studio_director import create_plan
        from app.studio_materials import create_material
        from app.studio_production import Produce, create_production
        from app.studio_schema import Create, PlanRequest
        from app.task_control import lock_task

        for permission in PERMISSIONS:
            require(run.effective_permissions, permission)
        claim = run.worker_id, run.claimed_at
        lock_task(session, run.task)
        session.refresh(run)
        if (run.worker_id, run.claimed_at) != claim:
            return "done"
        if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        verify_wrapper(session, run)
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        params = run.parameters
        kids = child_tasks(session, run)
        if not kids:
            from app.assistant_controller_tools import catalog
            from app.chat_providers import snapshot_provider
            from app.models import Conversation

            controller = session.get(Run, params["controller_parent_id"])
            frozen_provider = controller.parameters["controller_provider"]
            current_provider = snapshot_provider(
                session, session.get(Conversation, controller.conversation_id)
            )
            fields = ("provider", "provider_id", "location", "secret_ref", "provider_config_version")
            if any(current_provider.get(k) != frozen_provider.get(k) for k in fields):
                raise ValueError("The selected provider changed before Studio planning")
            # A managed model legitimately changes pending -> actual endpoint
            # when the controller's inference prerequisite finishes loading.
            # prepare_consumer resolves the same frozen model selection again.
            if (
                not str(frozen_provider["endpoint"]).startswith("llamacpp:")
                and current_provider["endpoint"] != frozen_provider["endpoint"]
            ):
                raise ValueError("The selected provider endpoint changed before Studio planning")
            intent = StudioIntent.model_validate(
                controller.metadata_json["controller_outcomes"][params["outcome_index"]]["studio"]
            )
            selected_context(session, controller.parameters.get("controller_creative_projects", {}), intent)
            aliases = next(
                s["arguments"]["references"]
                for s in controller.metadata_json["controller_steps"]
                if s["run_id"] == run.id
            )
            if (
                reference_ids(
                    session, owner_id=run.owner_id, entries=catalog(session, controller), aliases=aliases
                )
                != params["reference_artifact_ids"]
            ):
                raise ValueError("The frozen Studio references changed")
            # One transaction publishes material, planning Task and the receipt.
            material = create_material(
                session,
                Create(
                    client_request_id=uuid5(UUID(run.id), "material"),
                    title=params["title"],
                    brief=params["instruction"],
                    creative_project_id=params["creative_project_id"],
                    options=params["options"],
                ),
            )
            run.metadata_json = {**run.metadata_json, "studio_material_id": material.id}
            plan = create_plan(
                session,
                material.id,
                PlanRequest(
                    client_request_id=uuid5(UUID(run.id), "plan"),
                    expected_version=material.version,
                    model=params["model"],
                    reference_artifact_ids=params["reference_artifact_ids"],
                ),
                provider_snapshot=frozen_provider,
                frozen={
                    "brief": params["instruction"],
                    "options": params["options"],
                    "project_snapshot": params["project_snapshot"],
                },
            )
            attach(session, run, plan, "plan")
            kids = child_tasks(session, run)
        kind, primary = kids[-1]
        rows = stage_runs(session, kind, primary)
        if any(r.owner_id != run.owner_id for r in rows):
            raise ValueError("Studio stage crossed its owner boundary")
        active = [r for r in rows if r.status not in TERMINAL]
        if active:
            wait_for(session, run, active)
        else:
            if any(r.status != "succeeded" for r in rows):
                failures = [r for r in rows if r.error_message]
                failure = next((r for r in failures if r.error_type != "PrerequisiteFailed"), None)
                failure = failure or next(iter(failures), None)
                reason = (
                    f"{failure.executor_type}: {failure.error_message[:1000]}"
                    if failure
                    else "A required Run did not finish successfully"
                )
                raise ValueError(
                    f"Studio {kind} did not complete: {reason}. Finished results remain available."
                )
            if kind == "plan":
                revision = session.scalar(
                    select(StudioRevision).where(StudioRevision.source_run_id == primary.id)
                )
                if revision is None or revision.material_id != run.metadata_json["studio_material_id"]:
                    raise ValueError("The completed Studio storyboard is missing")
                # Cold native metadata verification is transient and starts no
                # generation. Keep the completed plan, release the worker slot
                # and use ordinary durable admission backoff before trying again.
                from app import studio_render
                from app.db import utcnow
                from app.events import append_event
                from app.resources import defer_resource_run

                readiness = studio_render.capabilities()
                if not readiness.get("available") and readiness.get("readiness") == "checking":
                    started = run.metadata_json.get("studio_renderer_check_started_at")
                    if started and utcnow() - datetime.fromisoformat(started) > timedelta(minutes=2):
                        raise ValueError(
                            "Studio renderer verification did not finish; inspect its readiness before continuing"
                        )
                    run.metadata_json = {
                        **run.metadata_json,
                        "studio_renderer_check_started_at": started or utcnow().isoformat(),
                    }
                    defer_resource_run(run)
                    append_event(
                        session,
                        run.id,
                        "studio.renderer.verifying",
                        {"reason": readiness.get("reason", "Checking the isolated renderer")},
                    )
                    wait_for(session, run, [])
                    session.commit()
                    return "done"
                production = create_production(
                    session,
                    revision.material_id,
                    Produce(
                        client_request_id=uuid5(UUID(run.id), "production"),
                        revision_id=revision.id,
                        presenter=run.parameters.get("presenter"),
                    ),
                )
                attach(session, run, production, "production")
                wait_for(session, run, stage_runs(session, "production", production))
            else:
                output = final_output(session, run)
                if output is None:
                    raise ValueError("Studio production has no complete final film")
                run.metadata_json = {
                    **run.metadata_json,
                    "controller_tool_result": {
                        "material_id": run.metadata_json["studio_material_id"],
                        "outcome_index": params["outcome_index"],
                        "options": params["options"],
                        "project": params["project_snapshot"].get("name"),
                        "artifact_id": output.id,
                        "requested_duration_seconds": params["options"]["duration_seconds"],
                        "actual_duration_seconds": output.metadata_json["frames"] / 30
                        if isinstance(output.metadata_json.get("frames"), int)
                        and output.metadata_json.get("fps") == 30
                        else None,
                    },
                }
                run.summary = "Complete Studio film is ready"
                transition(session, run, RunStatus.SUCCEEDED, event_type="studio.assistant.completed")
        session.commit()
        return "done"


def observed_result(session, root, step):
    from app.assistant_controller import verify_wrapper
    from app.assistant_controller_tools import subtree

    rows = subtree(session, root, step["run_id"])
    wrapper = rows[0]
    if wrapper.executor_type != NAME or len(rows) != 1:
        raise ValueError("Studio observation requires its composed tool")
    verify_wrapper(session, wrapper)
    if wrapper.status not in TERMINAL:
        return [wrapper], None
    output = final_output(session, wrapper) if wrapper.status == "succeeded" else None
    succeeded = output is not None
    aliases = (
        []
        if output is None
        else [
            {
                "alias": f"step:{step['index']}:video:1",
                "snapshot": {
                    "id": output.id,
                    "sha256": output.sha256,
                    "relative_path": output.relative_path,
                    "size_bytes": output.size_bytes,
                },
            }
        ]
    )
    return [], {
        "tool": "studio.produce",
        "status": "succeeded" if succeeded else "failed",
        "summaries": [wrapper.summary] if wrapper.summary else [],
        "responses": [],
        "errors": []
        if succeeded
        else [
            {
                "capability": "studio.produce",
                "status": wrapper.status,
                "error": wrapper.error_message[:1000] or "The complete film was not produced",
            }
        ],
        "artifacts": aliases,
        "produced_types": ["video"] if succeeded else [],
        "tool_data": [wrapper.metadata_json["controller_tool_result"]] if succeeded else [],
        "agent_ids": [],
        "studio_outcome_index": wrapper.parameters["outcome_index"],
        **(
            {"studio_attempt_exhausted": True}
            if any(
                kind == "plan"
                and child.status == "failed"
                and child.metadata_json.get("studio_planning_exhausted") is True
                for kind, child in child_tasks(session, wrapper)
            )
            else {}
        ),
    }
