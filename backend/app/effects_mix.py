"""Reopenable owned timeline mixes for an existing film and its generated stem."""

from uuid import UUID

from app.models import CreativeSession, CreativeTurn, Run, TimelineRevision
from app.timeline_schema import Manifest
from app.timelines import RenderRequest, create_timeline_run, digest, snapshots


def publish(session, run, artifact):
    prior = run.metadata_json.get("effects_preview_run_id")
    if prior:
        child = session.get(Run, prior)
        if (
            child is None
            or child.task_id != run.task_id
            or child.parent_run_id != run.id
            or child.executor_type != "timeline_render"
        ):
            raise ValueError("The saved sound mix belongs to another execution")
        return child
    mode = run.parameters.get("effects_mix")
    if not isinstance(mode, dict) or mode.get("preview_mode") != "mix":
        raise ValueError("A mixed preview requires its reviewed settings")
    v = run.parameters["video"]
    manifest = Manifest.model_validate(
        {
            "fps": v["fps"],
            "width": v["width"],
            "height": v["height"],
            "clips": [
                {
                    "artifact_id": run.parameters["video_artifact_id"],
                    "in_frame": 0,
                    "out_frame": v["frames"],
                    "gain": mode["original_gain"],
                }
            ],
            "tracks": [
                {"artifact_id": artifact.id, "duration_frames": v["frames"], "gain": mode["effects_gain"]}
            ],
        }
    )
    sources = snapshots(session, manifest)
    workspace = CreativeSession(
        capability="timeline", title=("Film sound · " + run.parameters["prompt"])[:160], draft={}
    )
    session.add(workspace)
    session.flush()
    value = manifest.model_dump(mode="json")
    revision = TimelineRevision(
        session_id=workspace.id,
        client_request_id=run.id,
        position=1,
        request_sha256=digest({"manifest": value, "parent_revision_id": None}),
        manifest=value,
        sources=sources,
    )
    session.add(revision)
    session.flush()
    render = RenderRequest(revision_id=UUID(revision.id), manifest=manifest)
    child = create_timeline_run(
        session,
        render,
        task=run.task,
        parent_run_id=run.id,
        observed_profile=run.parameters["effects_mix_renderer"],
    )
    child.parameters = {**child.parameters, "execution_deadline_at": run.parameters["execution_deadline_at"]}
    saved_request = render.model_dump(mode="json")
    session.add(
        CreativeTurn(
            session_id=workspace.id,
            task_id=run.task_id,
            run_id=child.id,
            client_request_id=run.id,
            position=1,
            feedback=run.parameters["prompt"],
            request_sha256=digest(
                {"parameters": saved_request, "parent_turn_id": None, "feedback": run.parameters["prompt"]}
            ),
            request_parameters={**saved_request, "_creative_request_kind": "direct"},
        )
    )
    workspace.draft = {
        "formState": {"manifest": value, "revision_id": revision.id, "preview_run_id": child.id}
    }
    run.metadata_json = {
        **run.metadata_json,
        "effects_preview_run_id": child.id,
        "effects_edit_session_id": workspace.id,
    }
    from app.dependencies import depend_on
    from app.events import append_event

    depend_on(session, child, run)
    append_event(
        session,
        run.id,
        "workflow.step.queued",
        {"run_id": child.id, "capability": child.capability, "edit_session_id": workspace.id},
    )
    return child
