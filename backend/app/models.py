"""ORM models. Portable types so PostgreSQL can replace SQLite later."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow


def new_id() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    capability: Mapped[str] = mapped_column(String(80), default="")
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    runs: Mapped[list[Run]] = relationship(back_populates="task")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("uq_run_task_operation", "task_id", "operation_key", unique=True),)
    operation_key: Mapped[str | None] = mapped_column(String(160), nullable=True)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_type: Mapped[str] = mapped_column(String(80), default="")
    capability: Mapped[str] = mapped_column(String(80), default="", index=True)
    executor_type: Mapped[str] = mapped_column(String(80), default="")
    execution_target: Mapped[str] = mapped_column(String(32), default="host")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow, index=True)
    queued_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    claimed_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    started_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    requested_resources: Mapped[dict] = mapped_column(JSON, default=dict)
    allocated_resources: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_gpu: Mapped[str] = mapped_column(String(32), default="none")
    actual_gpu: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    runner_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_log: Mapped[str] = mapped_column(String(500), default="")
    stderr_log: Mapped[str] = mapped_column(String(500), default="")
    error_type: Mapped[str] = mapped_column(String(120), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    cancellation_requested_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(80), default="user")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    effective_permissions: Mapped[list] = mapped_column(JSON, default=list)
    lease_expires_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    retry_class: Mapped[str] = mapped_column(String(32), default="inspect")
    summary: Mapped[str] = mapped_column(Text, default="")

    task: Mapped[Task] = relationship(back_populates="runs")
    events: Mapped[list[RunEvent]] = relationship(back_populates="run")


class RunDependency(Base):
    __tablename__ = "run_dependencies"
    __table_args__ = (CheckConstraint("run_id != prerequisite_id", name="no_self_dependency"),)

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    prerequisite_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True, index=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_event_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)

    run: Mapped[Run] = relationship(back_populates="events")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_type: Mapped[str] = mapped_column(String(40), index=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    relative_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(300), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    parent_artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    thumbnail_relative_path: Mapped[str] = mapped_column(String(500), default="")
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    library_updated_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    trashed_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    provider: Mapped[str] = mapped_column(String(80), default="local-openai-compatible")
    model: Mapped[str] = mapped_column(String(200), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    execution_mode: Mapped[str] = mapped_column(String(40), default="local")
    settings_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    auto_summary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)

    messages: Mapped[list[Message]] = relationship(back_populates="conversation")


class ChatWorkContext(Base):
    __tablename__ = "chat_work_contexts"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    selected_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class ChatTurnRequest(Base):
    __tablename__ = "chat_turn_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    user_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    repo_path: Mapped[str] = mapped_column(String(1000))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    integration_branch: Mapped[str] = mapped_column(String(200), default="develop")
    protected_branches: Mapped[list] = mapped_column(JSON, default=list)
    preferred_executor: Mapped[str] = mapped_column(String(40), default="cursor")
    test_commands: Mapped[list] = mapped_column(JSON, default=list)
    lint_commands: Mapped[list] = mapped_column(JSON, default=list)
    build_commands: Mapped[list] = mapped_column(JSON, default=list)
    agent_rules: Mapped[str] = mapped_column(Text, default="")
    pr_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class Worktree(Base):
    __tablename__ = "worktrees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    branch: Mapped[str] = mapped_column(String(300))
    relative_path: Mapped[str] = mapped_column(String(500))
    base_branch: Mapped[str] = mapped_column(String(200), default="")
    owned: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    removed_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    runtime: Mapped[str] = mapped_column(String(80), default="openai-compatible")
    provider: Mapped[str] = mapped_column(String(80), default="openai-compatible")
    model: Mapped[str] = mapped_column(String(200), default="")
    search_query: Mapped[str] = mapped_column(String(500), default="")
    fetch_urls: Mapped[list] = mapped_column(JSON, default=list)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    memory_scope: Mapped[str] = mapped_column(String(40), default="agent")
    trigger: Mapped[str] = mapped_column(String(40), default="manual")
    cron_expr: Mapped[str] = mapped_column(String(120), default="")
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    permission_profile: Mapped[str] = mapped_column(String(80), default="agent_minimal")
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    execution_target: Mapped[str] = mapped_column(String(32), default="host")
    maximum_runtime: Mapped[int] = mapped_column(Integer, default=600)
    retry_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    notification_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    output_expectation: Mapped[str] = mapped_column(Text, default="")
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    workflow_mode: Mapped[str] = mapped_column(String(20), default="sequential")
    tool_calling: Mapped[str] = mapped_column(String(20), default="none")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    next_run_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    last_status: Mapped[str] = mapped_column(String(32), default="")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text, default="")
    risk: Mapped[str] = mapped_column(String(40), default="medium")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    resolution: Mapped[str] = mapped_column(String(40), default="pending")


class MemoryEntry(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(40), index=True)
    scope_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    memory_type: Mapped[str] = mapped_column(String(40), default="fact")
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"

    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON)
    dimension: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(200), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class WorkerRow(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    last_heartbeat: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"
    __table_args__ = (Index("ix_telemetry_sampled", "sampled_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sampled_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    resolution: Mapped[str] = mapped_column(String(20), default="raw")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ResourceLock(Base):
    __tablename__ = "resource_locks"
    __table_args__ = (
        Index(
            "uq_resource_active",
            "resource_key",
            unique=True,
            sqlite_where=text("released_at IS NULL"),
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resource_key: Mapped[str] = mapped_column(String(80), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    granted_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    released_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)


class ModelFile(Base):
    __tablename__ = "model_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    host_path: Mapped[str] = mapped_column(String(1200), unique=True)
    filename: Mapped[str] = mapped_column(String(400))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0)
    format: Mapped[str] = mapped_column(String(40), default="")
    family: Mapped[str] = mapped_column(String(80), default="")
    quantization: Mapped[str] = mapped_column(String(40), default="")
    category: Mapped[str] = mapped_column(String(40), default="other", index=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    root_label: Mapped[str] = mapped_column(String(200), default="")
    discovered_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    last_scan_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    availability: Mapped[str] = mapped_column(String(20), default="unknown")


class ModelDefinition(Base):
    __tablename__ = "model_definitions"
    __table_args__ = (Index("uq_model_definitions_file_id", "file_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    family: Mapped[str] = mapped_column(String(80), default="")
    category: Mapped[str] = mapped_column(String(40), default="llm")
    file_id: Mapped[str | None] = mapped_column(ForeignKey("model_files.id"), nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="unverified", index=True)
    last_verify_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class Runtime(Base):
    __tablename__ = "runtimes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(80), default="")
    version: Mapped[str] = mapped_column(String(80), default="")


class RuntimeInstance(Base):
    __tablename__ = "runtime_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    runtime_key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    ownership: Mapped[str] = mapped_column(String(20), default="external")
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(40), default="unknown")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(80), default="http")
    status: Mapped[str] = mapped_column(String(40), default="unconfigured")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    config_json: Mapped[dict] = mapped_column("config", JSON, default=dict)
    secret_ref: Mapped[str] = mapped_column(String(200), default="")
    health: Mapped[str] = mapped_column(String(40), default="unknown")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class ChatProvider(Base):
    __tablename__ = "chat_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(80), default="openai-compatible")
    location: Mapped[str] = mapped_column(String(20), default="local")
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    secret_ref: Mapped[str] = mapped_column(String(200), default="")
    default_model: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class StationNode(Base):
    __tablename__ = "station_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(80), default="host-runner")
    ownership: Mapped[str] = mapped_column(String(20), default="remote")
    transport: Mapped[str] = mapped_column(String(40), default="unpublished")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    token_hash: Mapped[str] = mapped_column(String(128), default="")
    token_salt: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
    registered_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True)


class Notice(Base):
    __tablename__ = "notices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[Any | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    covered_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    covered_created_at: Mapped[Any] = mapped_column(UTCDateTime)
    covered_offset: Mapped[int] = mapped_column(Integer, default=0)
    source_message_ids: Mapped[list] = mapped_column(JSON)
    previous_summary_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime, default=utcnow)
