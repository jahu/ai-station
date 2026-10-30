"""Scoped memory with SQLite FTS5 retrieval."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import MemoryEntry


def _index_connection(session: Session, entry: MemoryEntry):
    """Typed index maintenance after ownership lookup, within this transaction.

    FTS5 cannot use ORM loader criteria. Never accept a caller's SQL or an
    unchecked memory ID as authority to mutate the shared index.
    """
    from app.data_access import DataAccessError, ScopedSession

    if isinstance(session, ScopedSession) and session.get(MemoryEntry, entry.id) is None:
        raise DataAccessError("Memory is unavailable")
    return session.connection()


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
        _index_connection(session, entry).execute(
            text("DELETE FROM memory_fts WHERE memory_id = :id"), {"id": entry.id}
        )
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
    _index_connection(session, entry).execute(
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
    tag: str | None = None,
    include_disabled: bool = False,
    limit: int = 30,
    offset: int = 0,
) -> list[MemoryEntry]:
    statement = select(MemoryEntry)
    if not include_disabled:
        statement = statement.where(MemoryEntry.enabled.is_(True))
    if scope:
        statement = statement.where(MemoryEntry.scope == scope)
    if scope_id is not None:
        statement = statement.where(MemoryEntry.scope_id == scope_id)
    if tag is not None:
        tags = func.json_each(MemoryEntry.tags).table_valued("value")
        statement = statement.where(select(tags.c.value).where(tags.c.value == tag).exists())
    if query.strip():
        # Apply scope/enabled filters BEFORE limiting results. Otherwise unrelated
        # high-ranking entries can hide every match in the requested scope.
        matches = (
            text(
                "SELECT memory_id, bm25(memory_fts) AS relevance FROM memory_fts "
                "WHERE memory_fts MATCH :memory_query"
            )
            .columns(memory_id=MemoryEntry.id.type, relevance=MemoryEntry.confidence.type)
            .subquery()
        )
        statement = (
            statement.join(matches, MemoryEntry.id == matches.c.memory_id)
            .order_by(MemoryEntry.pinned.desc(), matches.c.relevance, MemoryEntry.id)
            .params(memory_query=_fts_query(query))
        )
    else:
        statement = statement.order_by(
            MemoryEntry.pinned.desc(), MemoryEntry.updated_at.desc(), MemoryEntry.id
        )
    return list(session.scalars(statement.limit(limit).offset(offset)))


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
    connection = _index_connection(session, entry)
    connection.execute(text("DELETE FROM memory_fts WHERE memory_id = :id"), {"id": entry.id})
    connection.execute(text("DELETE FROM memory_embeddings WHERE memory_id = :id"), {"id": entry.id})
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
