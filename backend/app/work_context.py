"""Visible coding context and atomic Chat continuation of the same owned Task."""

from fastapi import HTTPException
from sqlalchemy import select

from app.coding_sessions import PROPOSALS, Followup, enqueue_followup
from app.db import utcnow
from app.models import ChatWorkContext, Message, ModelFile, Project, Run, Task, Worktree
from app.project_activity import project_write_condition
from app.state import TERMINAL


def project_context(session, conversation_id):
    binding = session.get(ChatWorkContext, conversation_id)
    if binding is not None and binding.task_id is None:
        return None
    query = select(Run).join(Task).where(Run.executor_type.in_(PROPOSALS))
    query = (
        query.where(Task.id == binding.task_id)
        if binding
        else query.where(Task.conversation_id == conversation_id)
    )
    source = session.scalar(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(1))
    if source is None:
        return None
    return context_of(session, source)


def selected_source(session, task_id, expected_run_id=None):
    task = session.get(Task, str(task_id))
    if task is None:
        raise HTTPException(404, "Coding task not found")
    source = session.scalar(
        select(Run)
        .where(Run.task_id == task.id, Run.executor_type.in_(PROPOSALS))
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    if source is None or expected_run_id is not None and source.id != str(expected_run_id):
        raise HTTPException(409, "Coding task changed; reload before selecting")
    worktree = session.get(Worktree, source.parameters.get("worktree_id", ""))
    if (
        not worktree
        or not worktree.owned
        or worktree.removed_at is not None
        or worktree.project_id != task.project_id
    ):
        raise HTTPException(409, "The owned task workspace is unavailable")
    return task, source


def context_of(session, source):
    task = session.get(Task, source.task_id)
    project = session.get(Project, task.project_id)
    worktree = session.get(Worktree, source.parameters.get("worktree_id", ""))
    safe_failure = source.status in {"failed", "canceled"} and (
        source.metadata_json.get("process_confirmed_gone")
        or not source.metadata_json.get("dispatch_attempted")
    )
    reason = None
    if not project or not worktree or not worktree.owned or worktree.removed_at is not None:
        reason = "The owned task workspace is unavailable."
    elif session.scalar(
        select(Run.id)
        .where(Run.project_id == task.project_id, Run.status.not_in(TERMINAL), project_write_condition())
        .limit(1)
    ):
        reason = "Wait for this project's active work to finish."
    elif source.status != "succeeded" and not safe_failure:
        reason = "Inspect the previous execution before continuing."
    model_key = source.parameters.get("model", "")
    model = (
        session.get(ModelFile, model_key.removeprefix("llamacpp:"))
        if model_key.startswith("llamacpp:")
        else None
    )
    model_label = (
        model.filename if model else source.parameters.get("model_selection", {}).get("name", model_key)
    )
    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "project_name": project.name if project else "Project",
        "title": task.title,
        "expected_run_id": source.id,
        "executor": source.executor_type.removesuffix("_proposal"),
        "model": model_key,
        "model_label": model_label,
        "external": source.executor_type != "local_proposal",
        "ready": reason is None,
        "reason": reason,
    }


def enqueue_continuation(session, conversation, user, body):
    scope = body.continuation
    task = session.get(Task, str(scope.task_id))
    binding = session.get(ChatWorkContext, conversation.id)
    allowed = (
        binding.task_id
        if binding is not None
        else task.id
        if task and task.conversation_id == conversation.id
        else None
    )
    if not task or allowed != task.id:
        raise HTTPException(422, "Choose a coding task belonging to this conversation")
    if (
        body.execution_mode not in {"work", "orchestrator", "assistant"}
        or body.action != "auto"
        or any(
            (
                body.coding,
                body.github,
                body.new_project,
                body.commit,
                body.publish,
                body.load,
                body.stop,
                body.attachments,
                body.image_artifact_ids,
                body.audio_artifact_id,
                body.web_search.enabled,
                body.reasoning,
                body.speech_text,
                body.upscale_result,
                body.media,
            )
        )
    ):
        raise HTTPException(422, "Continue the selected Work task without other actions or attachments")
    result = enqueue_followup(
        session,
        task.id,
        Followup(prompt=body.content, expected_run_id=scope.expected_run_id, external_ai=scope.external_ai),
        commit=False,
        conversation_id=conversation.id,
    )
    user.run_id = result["id"]
    user.metadata_json = {**user.metadata_json, "work_task_id": task.id}
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            run_id=result["id"],
            content="Continuing work in the existing project branch. Changes and validation will appear below.",
            metadata_json={"orchestration": True, "work_task_id": task.id},
        )
    )
    conversation.updated_at = utcnow()
    return result
