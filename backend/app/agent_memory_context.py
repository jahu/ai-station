"""Immutable own-agent/linked-project memory before isolated local execution."""

import json

from sqlalchemy import select

from app.models import Artifact, MemoryEntry
from app.permissions import require
from app.python_execution import read_owned_file


def verified_memory(session, source, definition, *, complete=False, for_execution=True):
    tool = source.parameters.get("tool")
    if tool not in {"memory_search", "project_memory"} or tool not in definition.tools:
        raise ValueError("Memory context lost its reviewed tool")
    scope = "agent" if tool == "memory_search" else "project"
    scope_id = source.agent_id if scope == "agent" else str(definition.project_id or "")
    if not scope_id or scope == "project" and source.project_id != scope_id:
        raise ValueError("Memory context lost its reviewed owner")
    if scope == "project":
        require(source.effective_permissions, "project_memory_read")
    artifacts = [
        a
        for a in session.scalars(select(Artifact).where(Artifact.run_id == source.id))
        if a.metadata_json.get("tool") == tool and a.artifact_type == "json"
    ]
    if len(artifacts) != 1 or artifacts[0].trashed_at is not None:
        raise ValueError("Memory context is missing its original source artifact")
    artifact = artifacts[0]
    if artifact.mime_type != "application/json":
        raise ValueError("Memory context lost its JSON source")
    path = read_owned_file(artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=1000000)
    data = json.loads(path.read_bytes())
    observation = source.metadata_json.get("observation")
    if (
        data != observation
        or data.get("scope") != scope
        or data.get("scope_id") != scope_id
        or not isinstance(data.get("entries"), list)
        or len(data["entries"]) > 20
    ):
        raise ValueError("Memory context differs from its recorded owner or snapshot")
    seen = set()
    for entry in data["entries"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or entry["id"] in seen
            or not isinstance(entry.get("content"), str)
            or len(entry["content"]) > 12000
            or not isinstance(entry.get("updated_at"), str)
        ):
            raise ValueError("Memory context contains an invalid entry")
        seen.add(entry["id"])
        if for_execution:
            current = session.get(MemoryEntry, entry["id"], populate_existing=True)
            if (
                current is None
                or not current.enabled
                or current.scope != scope
                or current.scope_id != scope_id
                or current.content != entry["content"]
                or current.updated_at.isoformat() != entry["updated_at"]
                or any(
                    entry.get(key) != getattr(current, key)
                    for key in ("source_run_id", "source_conversation_id", "source_message_id")
                )
            ):
                raise ValueError("Saved memory changed or was disabled after capture; review and run again")
    result = {**data, "untrusted": True}
    if not complete:
        result["entries"] = [
            {**entry, "content": entry["content"][:1000], "excerpted": len(entry["content"]) > 1000}
            for entry in data["entries"]
        ]
    return artifact, result, []
