"""Executors. Capability-specific logic stays here, not in the run table."""

from __future__ import annotations

import json
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_drafts import AgentDraftExecutor
from app.agent_executor import LocalAgentExecutor
from app.agent_media import AgentMediaExecutor
from app.agent_page_coding import AgentPageCodingExecutor
from app.agent_result_alert import ResultAlertExecutor
from app.agent_workflow import AgentToolExecutor, AgentWorkflowExecutor
from app.artifact_purge import ArtifactPurgeExecutor
from app.artifacts import adopt_existing
from app.assistant import AssistantExecutor
from app.audio import AudioExecutor
from app.avatars import AvatarExecutor
from app.browser import BrowserExecutor
from app.chat_executor import ChatExecutor
from app.chat_reasoning import ReasoningCheckExecutor
from app.codex_coding import CodexProposalExecutor
from app.commit_executor import ReviewedCommitExecutor
from app.config import get_settings
from app.connectors import HttpConnectorExecutor
from app.conversation_agent_control import AgentControlExecutor
from app.cursor_executor import CursorProposalExecutor
from app.data_agents import DataGenerateExecutor, DataResultExecutor
from app.data_inputs import DataInspectionExecutor
from app.email_delivery import EmailCheckExecutor, EmailSendExecutor
from app.embeddings import MemoryEmbedExecutor
from app.events import append_event
from app.github_connector import GithubReadExecutor
from app.llama import LlamaExecutor, LlamaHealthExecutor
from app.llama_handoff import LlamaResumeConsumerExecutor
from app.local_coding import LocalProposalExecutor
from app.maintenance import SqliteBackupExecutor
from app.market_feeds import MarketFeedExecutor
from app.market_watch import MarketExecutor
from app.media_jobs import AvatarPlannerExecutor, CompositionExecutor
from app.media_translation import MediaTranslationExecutor, TranslationApplyExecutor
from app.model_definitions import ModelInstallExecutor
from app.model_registry import ModelDiscoveryExecutor
from app.models import Conversation, MemoryEntry, Message, Project, Run, Worktree
from app.music import MusicExecutor
from app.paths import safe_join, validate_relative
from app.photo_executor import PhotoPipeExecutor
from app.private_ui import PrivateAccessExecutor
from app.project_checks import ProjectPlanExecutor
from app.project_dependencies import ProjectDependenciesExecutor
from app.project_setup import ProjectSetupExecutor
from app.providers import ProviderError, stream_chat
from app.publication import GithubPublicationExecutor, PublicationReconcileExecutor
from app.python_execution import PythonExecutor
from app.resources import release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import mark_failed, touch_lease, transition
from app.runtime_registry import RuntimeObservationExecutor
from app.site_preview_executor import PreviewActionExecutor, PreviewCloseExecutor, PreviewExecutor
from app.state import RunStatus
from app.station_snapshot import StationSnapshotExecutor
from app.summary_executor import SummaryExecutor
from app.tools import get_tool
from app.transcription import TranscriptionExecutor
from app.validation_executor import ProjectValidationExecutor
from app.video import VideoExecutor
from app.worktree_executor import WorktreeExecutor
from app.worktree_remove import WorktreeRemoveExecutor


class ExecutorResult(str):
    pass


REQUEUED = "requeued"
DONE = "done"


def _runner() -> RunnerClient:
    return RunnerClient()


def _gpu_indexes(runner: RunnerClient) -> list[int]:
    payload = runner.hardware()
    return [int(item["index"]) for item in payload.get("gpus") or []]


def _requeue(session: Session, run: Run, reason: str) -> str:
    if run.status != RunStatus.INTERRUPTED.value:
        transition(
            session, run, RunStatus.INTERRUPTED, event_type="run.interrupted", payload={"reason": reason}
        )
    run.finished_at = None
    run.worker_id = None
    run.lease_expires_at = None
    transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"reason": reason})
    run.queued_at = run.created_at
    release_run_locks(session, run.id)
    return REQUEUED


def _canceled(session: Session, run: Run) -> bool:
    session.refresh(run)
    return run.status == RunStatus.CANCEL_REQUESTED.value


class CodingExecutor:
    name = "coding"

    def execute(self, session: Session, run: Run) -> str:
        runner = _runner()
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        session.commit()
        project = session.get(Project, run.project_id) if run.project_id else None
        if project is None:
            mark_failed(session, run, "ProjectMissing", "Coding runs require a registered project")
            return DONE
        slug = _slug(run.parameters.get("title") or project.name)
        branch = f"ai/{run.id[:8]}-{slug}"
        relative = validate_relative(f"worktrees/{project.id}/{run.id}")
        try:
            runner.create_worktree(
                {
                    "repo_path": project.repo_path,
                    "relative_path": relative,
                    "branch": branch,
                    "base_branch": project.default_branch,
                }
            )
        except (RunnerUnavailable, RunnerError) as exc:
            mark_failed(session, run, type(exc).__name__, str(exc))
            return DONE
        session.add(
            Worktree(
                project_id=project.id,
                run_id=run.id,
                branch=branch,
                relative_path=relative,
                base_branch=project.default_branch,
            )
        )
        append_event(session, run.id, "git.worktree.created", {"branch": branch, "path": relative})
        prompt = _coding_prompt(run, project, branch)
        try:
            started = runner.start_coding(
                {
                    "run_id": run.id,
                    "executor": run.executor_type,
                    "workspace_relative": relative,
                    "prompt": prompt,
                    "model": run.parameters.get("model") or "",
                }
            )
        except (RunnerUnavailable, RunnerError) as exc:
            mark_failed(session, run, type(exc).__name__, str(exc))
            return DONE
        run.pid = started.get("pid")
        run.process_group_id = started.get("process_group_id")
        run.stdout_log = started.get("stdout_log") or ""
        run.stderr_log = started.get("stderr_log") or ""
        transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={"branch": branch})
        session.commit()
        result = _poll_process(session, run, runner, output_relative=None, artifact_type=None)
        if run.status != RunStatus.SUCCEEDED.value:
            return result
        _collect_git_review(session, run, runner, project, relative, branch)
        session.commit()
        return DONE


class LocalCodingExecutor:
    """Experimental loop. Tools stay inside the allocated worktree."""

    name = "local_coding"

    def __init__(self, complete=None):
        self.complete = complete

    def execute(self, session: Session, run: Run) -> str:
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        if self.complete is None:
            mark_failed(
                session,
                run,
                "NotConfigured",
                "Local coding needs a configured local model. No completer is available for this run.",
            )
            return DONE
        relative = run.parameters.get("workspace_relative")
        if not relative:
            mark_failed(session, run, "WorktreeMissing", "Local coding requires an existing worktree")
            return DONE
        transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={})
        transcript = []
        for step in range(8):
            if _canceled(session, run):
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
                return DONE
            raw = self.complete(run.parameters.get("prompt", ""), transcript)
            append_event(session, run.id, "agent.message", {"step": step, "text": raw[:4000]})
            try:
                action = json.loads(raw)
            except json.JSONDecodeError:
                run.summary = raw[:4000]
                break
            if "final" in action:
                run.summary = str(action["final"])[:4000]
                break
            tool_name = action.get("tool")
            spec = get_tool(tool_name or "")
            if spec is None or not spec.operational:
                append_event(session, run.id, "tool.failed", {"tool": tool_name, "error": "unavailable"})
                transcript.append({"tool": tool_name, "error": "unavailable"})
                continue
            if spec.name not in set(run.effective_permissions) and not _permitted(
                run, spec.required_permissions
            ):
                append_event(session, run.id, "tool.failed", {"tool": tool_name, "error": "permission"})
                continue
            append_event(session, run.id, "tool.started", {"tool": tool_name})
            try:
                output = _local_tool(run, relative, action)
            except (RunnerError, RunnerUnavailable, ValueError) as exc:
                append_event(session, run.id, "tool.failed", {"tool": tool_name, "error": str(exc)})
                transcript.append({"tool": tool_name, "error": str(exc)})
                continue
            append_event(session, run.id, "tool.completed", {"tool": tool_name})
            transcript.append({"tool": tool_name, "output": output})
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return DONE


class AgentExecutor:
    name = "agent"

    def execute(self, session: Session, run: Run) -> str:
        from app.models import Agent

        agent = session.get(Agent, run.agent_id) if run.agent_id else None
        if agent is None:
            mark_failed(session, run, "AgentMissing", "Agent run has no agent")
            return DONE
        transition(
            session, run, RunStatus.RUNNING, event_type="executor.started", payload={"agent": agent.name}
        )
        body = (
            f"Goal:\n{agent.goal}\n\n"
            f"Output expectation:\n{agent.output_expectation}\n\n"
            "Write a concise result for the user. Do not claim actions that were not performed."
        )
        model = agent.model or get_settings().llm_model
        text = ""
        if model:
            try:
                text = "".join(
                    stream_chat(
                        [
                            {"role": "system", "content": agent.system_prompt},
                            {"role": "user", "content": body},
                        ],
                        model=model,
                        temperature=0.3,
                        max_tokens=1200,
                    )
                )
            except ProviderError as exc:
                text = f"The configured model could not be reached ({exc})."
        else:
            text = "No model is configured. The agent recorded its goal and stopped without calling a model."
        import tempfile

        from app.artifacts import register_file

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        register_file(
            session,
            source=temp_path,
            artifact_type="markdown",
            mime_type="text/markdown",
            original_filename=f"{agent.name}.md",
            run_id=run.id,
            metadata={"agent_id": agent.id},
        )
        temp_path.unlink(missing_ok=True)
        run.summary = text[:500]
        agent.last_status = "succeeded"
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return DONE


class FakeExecutor:
    name = "fake"

    def execute(self, session: Session, run: Run) -> str:
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        transition(session, run, RunStatus.RUNNING, event_type="executor.started", payload={})
        append_event(session, run.id, "stdout", {"text": "fake executor ok\n"})
        run.summary = "fake executor ok"
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return DONE


# Activate adapters only after their vertical slice is verified end to end.

EXECUTORS = {
    "media_translate": MediaTranslationExecutor(),
    "media_translation_apply": TranslationApplyExecutor(),
    "artifact_purge": ArtifactPurgeExecutor(),
    "private_access": PrivateAccessExecutor(),
    "site_preview": PreviewExecutor(),
    "site_preview_action": PreviewActionExecutor(),
    "site_preview_close": PreviewCloseExecutor(),
    "browser": BrowserExecutor(),
    "python": PythonExecutor(),
    "project_setup": ProjectSetupExecutor(),
    "data_inspection": DataInspectionExecutor(),
    "agent_data_generate": DataGenerateExecutor(),
    "agent_data_result": DataResultExecutor(),
    "agent_result_alert": ResultAlertExecutor(),
    "fake": FakeExecutor(),
    "orchestrator": AssistantExecutor(),
    "station_snapshot": StationSnapshotExecutor(),
    "llama_load": LlamaExecutor("load"),
    "llama_stop": LlamaExecutor("stop"),
    "llama_health": LlamaHealthExecutor(),
    "llama_resume_consumer": LlamaResumeConsumerExecutor(),
    "photo_pipe": PhotoPipeExecutor(),
    "chatterbox": AudioExecutor(),
    "ace_step_music": MusicExecutor(),
    "whisper_transcribe": TranscriptionExecutor(),
    "echomimic": AvatarExecutor(),
    "wan_video": VideoExecutor(),
    CompositionExecutor.name: CompositionExecutor(),
    AvatarPlannerExecutor.name: AvatarPlannerExecutor(),
    "reviewed_commit": ReviewedCommitExecutor(),
    "github_publication": GithubPublicationExecutor(),
    "publication_reconcile": PublicationReconcileExecutor(),
    "chat": ChatExecutor(),
    "reasoning_check": ReasoningCheckExecutor(),
    "chat_summary": SummaryExecutor(),
    "worktree_prepare": WorktreeExecutor(),
    "worktree_remove": WorktreeRemoveExecutor(),
    "project_validation": ProjectValidationExecutor(),
    "project_dependencies": ProjectDependenciesExecutor(),
    "project_plan": ProjectPlanExecutor(),
    "cursor_proposal": CursorProposalExecutor(),
    "codex_proposal": CodexProposalExecutor(),
    "local_proposal": LocalProposalExecutor(),
    "model_discovery": ModelDiscoveryExecutor(),
    "model_install": ModelInstallExecutor(),
    "agent": LocalAgentExecutor(),
    "agent_workflow": AgentWorkflowExecutor(),
    "agent_media": AgentMediaExecutor(),
    "agent_draft": AgentDraftExecutor(),
    "agent_control": AgentControlExecutor(),
    "agent_tool": AgentToolExecutor(),
    "agent_market": MarketExecutor(),
    "market_feed": MarketFeedExecutor(),
    "email_check": EmailCheckExecutor(),
    "email_send": EmailSendExecutor(),
    "agent_page_coding": AgentPageCodingExecutor(),
    "http_connector": HttpConnectorExecutor(),
    "github_read": GithubReadExecutor(),
    "memory_embed": MemoryEmbedExecutor(),
    "sqlite_backup": SqliteBackupExecutor(),
    "runtime_observation": RuntimeObservationExecutor(),
}


def _output_relative(run: Run) -> str:
    return validate_relative(f"artifacts/{run.id[:2]}/{run.id[2:4]}/{run.id}.png")


def _poll_process(
    session: Session,
    run: Run,
    runner: RunnerClient,
    *,
    output_relative: str | None,
    artifact_type: str | None,
) -> str:
    offset = 0
    while True:
        touch_lease(session, run)
        if _canceled(session, run):
            try:
                runner.cancel_process(run.id)
            except (RunnerUnavailable, RunnerError) as exc:
                append_event(session, run.id, "run.cancel_requested", {"error": str(exc)})
        try:
            info = runner.inspect_process(run.id)
        except RunnerError as exc:
            mark_failed(session, run, "RunnerError", exc.detail)
            release_run_locks(session, run.id)
            return DONE
        except RunnerUnavailable as exc:
            mark_failed(session, run, "RunnerUnavailable", str(exc))
            release_run_locks(session, run.id)
            return DONE
        chunk = (info.get("stdout") or "")[offset:]
        if chunk:
            append_event(session, run.id, "stdout", {"text": chunk[-8000:]})
            offset = len(info.get("stdout") or "")
        session.commit()
        status = info.get("status")
        if status in {"exited", "canceled"}:
            break
        time.sleep(0.4)
    session.refresh(run)
    release_run_locks(session, run.id)
    if run.status == RunStatus.CANCEL_REQUESTED.value or info.get("status") == "canceled":
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
        return DONE
    if info.get("exit_code") not in (0, None):
        mark_failed(session, run, "ExitCode", info.get("stderr_tail") or f"exit {info.get('exit_code')}")
        return DONE
    if output_relative and artifact_type:
        try:
            adopt_existing(
                session,
                relative_path=output_relative,
                artifact_type=artifact_type,
                mime_type="image/png",
                original_filename=Path(output_relative).name,
                run_id=run.id,
                metadata={"capability": run.capability, "backend": run.parameters.get("backend")},
                parent_artifact_ids=run.parameters.get("parent_artifact_ids") or [],
            )
        except FileNotFoundError:
            mark_failed(session, run, "OutputMissing", "The pipeline finished without an output file")
            return DONE
    if run.status == RunStatus.RUNNING.value:
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
    return DONE


def _collect_git_review(session, run, runner, project, relative, branch) -> None:
    settings = get_settings()
    workspace = safe_join(settings.data_dir, relative)
    try:
        diff = runner.git_diff({"repo_path": str(workspace), "base": project.default_branch})
        status = runner.git_status({"repo_path": str(workspace)})
    except (RunnerUnavailable, RunnerError) as exc:
        append_event(session, run.id, "git.diff.generated", {"error": str(exc)})
        return
    import tempfile

    from app.artifacts import register_file

    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as handle:
        handle.write(diff.get("diff") or "")
        temp = Path(handle.name)
    register_file(
        session,
        source=temp,
        artifact_type="git_diff",
        mime_type="text/x-diff",
        original_filename=f"{branch}.diff",
        run_id=run.id,
        metadata={"branch": branch, "status": status},
    )
    temp.unlink(missing_ok=True)
    append_event(session, run.id, "git.diff.generated", {"branch": branch})
    results = []
    for kind, commands in (
        ("test", project.test_commands or []),
        ("lint", project.lint_commands or []),
        ("build", project.build_commands or []),
    ):
        for argv in commands:
            try:
                completed = runner.run_project_command(
                    {"repo_path": str(workspace), "argv": argv, "kind": kind, "allowed": commands}
                )
            except (RunnerUnavailable, RunnerError) as exc:
                completed = {"exit_code": 1, "stderr": str(exc), "stdout": ""}
            results.append({"kind": kind, "argv": argv, **completed})
            append_event(
                session,
                run.id,
                "tool.completed" if completed.get("exit_code") == 0 else "tool.failed",
                {"kind": kind, "argv": argv, "exit_code": completed.get("exit_code")},
            )
    run.metadata_json = {**(run.metadata_json or {}), "validation": results, "branch": branch}
    policy = project.pr_policy or {}
    if policy.get("commit_task_branch") and status.get("dirty"):
        try:
            committed = runner.git_commit(
                {
                    "repo_path": str(workspace),
                    "branch": branch,
                    "protected": project.protected_branches,
                    "message": f"AI Station: {run.parameters.get('title') or branch}",
                }
            )
            append_event(session, run.id, "git.commit.created", committed)
        except (RunnerUnavailable, RunnerError) as exc:
            append_event(session, run.id, "tool.failed", {"tool": "git_commit", "error": str(exc)})


def _coding_prompt(run: Run, project: Project, branch: str) -> str:
    return (
        f"You are working in an isolated git worktree on branch {branch}.\n"
        f"Project: {project.name}\n"
        f"Repository rules:\n{project.agent_rules}\n\n"
        "Do not push, merge, or touch protected branches.\n"
        f"Task:\n{run.parameters.get('prompt', '')}\n"
    )


def _chat_messages(session: Session, conversation: Conversation) -> list[dict]:
    pinned = session.scalars(
        select(MemoryEntry).where(
            MemoryEntry.enabled.is_(True),
            MemoryEntry.pinned.is_(True),
            MemoryEntry.scope == "conversation",
            MemoryEntry.scope_id == conversation.id,
        )
    ).all()
    summary = session.scalar(
        select(MemoryEntry)
        .where(
            MemoryEntry.scope == "conversation",
            MemoryEntry.scope_id == conversation.id,
            MemoryEntry.memory_type == "summary",
            MemoryEntry.enabled.is_(True),
        )
        .order_by(MemoryEntry.created_at.desc())
    )
    history = session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    ).all()
    recent = history[-16:]
    messages = []
    system_parts = []
    if conversation.system_prompt:
        system_parts.append(conversation.system_prompt)
    if summary:
        system_parts.append("Rolling summary:\n" + summary.content)
    if pinned:
        system_parts.append("Pinned context:\n" + "\n".join(item.content for item in pinned))
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    for item in recent:
        if item.role in {"user", "assistant", "system"}:
            messages.append({"role": item.role, "content": item.content})
    return messages


def _save_assistant(session, conversation, text: str, run: Run, *, partial: bool) -> None:
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=text,
            run_id=run.id,
            metadata_json={"partial": partial},
        )
    )
    conversation.updated_at = run.started_at or conversation.updated_at
    if conversation.title == "New conversation":
        user = session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.role == "user")
            .order_by(Message.created_at)
        )
        if user:
            conversation.title = user.content[:80]
    _maybe_summarize(session, conversation)


def _maybe_summarize(session, conversation: Conversation) -> None:
    from app.memory import upsert_memory

    history = session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    ).all()
    if len(history) < 24:
        return
    older = history[:-16]
    content = "\n".join(f"{item.role}: {item.content[:240]}" for item in older[-20:])
    upsert_memory(
        session,
        scope="conversation",
        scope_id=conversation.id,
        memory_type="summary",
        content=content,
        tags=["summary"],
        source_conversation_id=conversation.id,
    )


def _permitted(run: Run, required: tuple[str, ...]) -> bool:
    granted = set(run.effective_permissions or [])
    return all(item in granted for item in required)


def _local_tool(run: Run, relative: str, action: dict) -> dict:
    runner = _runner()
    settings = get_settings()
    workspace = str(safe_join(settings.data_dir, relative))
    name = action.get("tool")
    args = action.get("arguments") or {}
    if name == "read_file":
        return runner.read_file({"root": workspace, "path": args["path"]})
    if name == "list_directory":
        return runner.list_dir({"root": workspace, "path": args.get("path", ".")})
    if name == "search_files":
        return runner.search_files({"root": workspace, "query": args["query"]})
    if name == "write_file":
        return runner.write_file({"root": workspace, "path": args["path"], "content": args["content"]})
    if name == "apply_patch":
        return runner.apply_patch({"repo_path": workspace, "diff": args["diff"]})
    if name == "git_status":
        return runner.git_status({"repo_path": workspace})
    if name == "git_diff":
        return runner.git_diff({"repo_path": workspace, "base": None})
    if name == "run_project_command":
        project_commands = run.parameters.get("allowed_commands") or []
        kind = args.get("kind")
        argv = args.get("argv")
        return runner.run_project_command(
            {"repo_path": workspace, "argv": argv, "kind": kind, "allowed": project_commands}
        )
    raise ValueError(f"Unsupported tool {name}")


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:40] or "task"
