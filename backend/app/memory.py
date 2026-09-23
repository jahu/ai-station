"""Scoped memory with SQLite FTS5 retrieval."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import MemoryEntry


def upsert_memory(
    session: Session,
    *,
    scope: str,
    content: str,
    memory_type: str = "fact",
    scope_id: str = "",
    tags: list[str] | None = None,
    confidence: float | None = None,
    pinned: bool = False,
    source_run_id: str | None = None,
    source_conversation_id: str | None = None,
    source_message_id: str | None = None,
    entry_id: str | None = None,
) -> MemoryEntry:
    if scope not in {"conversation", "agent", "project", "global"}:
        raise ValueError("Unknown memory scope")
    if entry_id:
        entry = session.get(MemoryEntry, entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.content = content
        entry.memory_type = memory_type
        entry.tags = tags or []
        entry.confidence = confidence
        entry.pinned = pinned
        entry.updated_at = utcnow()
        session.execute(text("DELETE FROM memory_fts WHERE memory_id = :id"), {"id": entry.id})
    else:
        entry = MemoryEntry(
            scope=scope,
            scope_id=scope_id,
            memory_type=memory_type,
            content=content,
            tags=tags or [],
            confidence=confidence,
            pinned=pinned,
            source_run_id=source_run_id,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
        )
        session.add(entry)
        session.flush()
    session.execute(
        text("INSERT INTO memory_fts(memory_id, content, tags) VALUES (:id, :content, :tags)"),
        {"id": entry.id, "content": entry.content, "tags": " ".join(entry.tags or [])},
    )
    session.flush()
    return entry


def search_memory(
    session: Session,
    query: str,
    *,
    scope: str | None = None,
    scope_id: str | None = None,
    limit: int = 30,
) -> list[MemoryEntry]:
    statement = select(MemoryEntry).where(MemoryEntry.enabled.is_(True))
    if scope:
        statement = statement.where(MemoryEntry.scope == scope)
    if scope_id is not None:
        statement = statement.where(MemoryEntry.scope_id == scope_id)
    if query.strip():
        rows = session.execute(
            text(
                "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH :q "
                "ORDER BY bm25(memory_fts) LIMIT :limit"
            ),
            {"q": _fts_query(query), "limit": limit},
        ).all()
        ids = [row[0] for row in rows]
        if not ids:
            return []
        statement = statement.where(MemoryEntry.id.in_(ids))
        found = list(session.scalars(statement))
        order = {memory_id: index for index, memory_id in enumerate(ids)}
        found.sort(key=lambda item: (not item.pinned, order.get(item.id, 999)))
        return found[:limit]
    statement = statement.order_by(MemoryEntry.pinned.desc(), MemoryEntry.updated_at.desc()).limit(limit)
    return list(session.scalars(statement))


def disable_memory(session: Session, entry_id: str) -> MemoryEntry:
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        raise KeyError(entry_id)
    entry.enabled = False
    entry.updated_at = utcnow()
    return entry


def delete_memory(session: Session, entry_id: str) -> None:
    entry = session.get(MemoryEntry, entry_id)
    if entry is None:
        raise KeyError(entry_id)
    session.execute(text("DELETE FROM memory_fts WHERE memory_id = :id"), {"id": entry.id})
    session.delete(entry)


def _fts_query(query: str) -> str:
    tokens = [token for token in re_tokens(query) if token]
    if not tokens:
        return '""'
    return " AND ".join(f'"{token}"' for token in tokens)


def re_tokens(query: str) -> list[str]:
    cleaned = []
    current = []
    for char in query:
        if char.isalnum() or char in {"_", "-"}:
            current.append(char)
        else:
            if current:
                cleaned.append("".join(current))
                current = []
    if current:
        cleaned.append("".join(current))
    return cleaned
