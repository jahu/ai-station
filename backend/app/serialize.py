"""JSON helpers for ORM rows."""

from __future__ import annotations

from app.models import (
    Agent,
    Approval,
    Artifact,
    Conversation,
    MemoryEntry,
    Message,
    ModelFile,
    Project,
    RuntimeInstance,
    Task,
    Worktree,
)


def iso(value) -> str | None:
    return value.isoformat() if value else None


def task_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "intent": task.intent,
        "status": task.status,
        "capability": task.capability,
        "project_id": task.project_id,
        "conversation_id": task.conversation_id,
        "agent_id": task.agent_id,
        "created_at": iso(task.created_at),
        "metadata": task.metadata_json,
    }


def artifact_dict(artifact: Artifact) -> dict:
    return {
        "id": artifact.id,
        "type": artifact.artifact_type,
        "mime_type": artifact.mime_type,
        "relative_path": artifact.relative_path,
        "original_filename": artifact.original_filename,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "created_at": iso(artifact.created_at),
        "run_id": artifact.run_id,
        "metadata": artifact.metadata_json,
        "parent_artifact_ids": artifact.parent_artifact_ids,
        "thumbnail_relative_path": artifact.thumbnail_relative_path,
        "title": artifact.title,
        "notes": artifact.notes,
        "library_updated_at": iso(artifact.library_updated_at),
        "trashed_at": iso(artifact.trashed_at),
    }


def conversation_dict(conversation: Conversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "provider": conversation.provider,
        "model": conversation.model,
        "system_prompt": conversation.system_prompt,
        "temperature": conversation.temperature,
        "max_tokens": conversation.max_tokens,
        "execution_mode": conversation.execution_mode,
        "auto_summary": conversation.auto_summary,
        "created_at": iso(conversation.created_at),
        "updated_at": iso(conversation.updated_at),
    }


def message_dict(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "run_id": message.run_id,
        "created_at": iso(message.created_at),
        "metadata": message.metadata_json,
    }


def project_dict(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "repo_path": project.repo_path,
        "default_branch": project.default_branch,
        "integration_branch": project.integration_branch,
        "protected_branches": project.protected_branches,
        "preferred_executor": project.preferred_executor,
        "test_commands": project.test_commands,
        "lint_commands": project.lint_commands,
        "build_commands": project.build_commands,
        "agent_rules": project.agent_rules,
        "pr_policy": project.pr_policy,
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


def worktree_dict(worktree: Worktree) -> dict:
    return {
        "id": worktree.id,
        "project_id": worktree.project_id,
        "run_id": worktree.run_id,
        "branch": worktree.branch,
        "relative_path": worktree.relative_path,
        "base_branch": worktree.base_branch,
        "owned": worktree.owned,
        "created_at": iso(worktree.created_at),
        "removed_at": iso(worktree.removed_at),
        "expires_at": iso(worktree.expires_at),
    }


def agent_dict(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "goal": agent.goal,
        "system_prompt": agent.system_prompt,
        "runtime": agent.runtime,
        "provider": agent.provider,
        "model": agent.model,
        "tools": agent.tools,
        "search_query": agent.search_query,
        "fetch_urls": agent.fetch_urls,
        "skills": agent.skills,
        "memory_scope": agent.memory_scope,
        "trigger": agent.trigger,
        "cron_expr": agent.cron_expr,
        "interval_seconds": agent.interval_seconds,
        "run_at": iso(agent.run_at),
        "permission_profile": agent.permission_profile,
        "project_id": agent.project_id,
        "execution_target": agent.execution_target,
        "maximum_runtime": agent.maximum_runtime,
        "retry_policy": agent.retry_policy,
        "notification_policy": agent.notification_policy,
        "output_expectation": agent.output_expectation,
        "require_approval": agent.require_approval,
        "workflow_mode": agent.workflow_mode,
        "enabled": agent.enabled,
        "last_run_at": iso(agent.last_run_at),
        "next_run_at": iso(agent.next_run_at),
        "last_status": agent.last_status,
        "failure_count": agent.failure_count,
    }


def memory_dict(entry: MemoryEntry) -> dict:
    return {
        "id": entry.id,
        "scope": entry.scope,
        "scope_id": entry.scope_id,
        "memory_type": entry.memory_type,
        "content": entry.content,
        "tags": entry.tags,
        "confidence": entry.confidence,
        "pinned": entry.pinned,
        "enabled": entry.enabled,
        "source_run_id": entry.source_run_id,
        "source_conversation_id": entry.source_conversation_id,
        "source_message_id": entry.source_message_id,
        "created_at": iso(entry.created_at),
        "updated_at": iso(entry.updated_at),
    }


def approval_dict(approval: Approval) -> dict:
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "action": approval.action,
        "reason": approval.reason,
        "risk": approval.risk,
        "payload": approval.payload,
        "requested_at": iso(approval.requested_at),
        "resolved_at": iso(approval.resolved_at),
        "resolution": approval.resolution,
    }


def model_dict(row: ModelFile) -> dict:
    return {
        "id": row.id,
        "host_path": row.host_path,
        "filename": row.filename,
        "size_bytes": row.size_bytes,
        "mtime": row.mtime,
        "format": row.format,
        "family": row.family,
        "quantization": row.quantization,
        "category": row.category,
        "capabilities": row.capabilities,
        "root_label": row.root_label,
    }


def runtime_dict(row: RuntimeInstance) -> dict:
    return {
        "id": row.id,
        "runtime_key": row.runtime_key,
        "name": row.name,
        "ownership": row.ownership,
        "endpoint": row.endpoint,
        "status": row.status,
        "metadata": row.metadata_json,
        "updated_at": iso(row.updated_at),
    }
