from alembic import command
from app.db import alembic_config, migrate, session_factory
from app.memory import upsert_memory
from app.models import Conversation, MemoryEntry
from app.personal_memory import preferences
from sqlalchemy import select, text


def test_upgrade_preserves_memories_sources_and_defaults_without_opt_in(session):
    conversation = Conversation(model="test", title="Existing conversation")
    session.add(conversation)
    session.flush()
    memory = upsert_memory(
        session,
        scope="global",
        content="Existing pinned preference",
        pinned=True,
        source_conversation_id=conversation.id,
    )
    session.commit()
    cid, mid = conversation.id, memory.id
    session.close()
    command.downgrade(alembic_config(), "0047")
    migrate()
    migrate()
    with session_factory()() as db:
        entry = db.get(MemoryEntry, mid)
        assert entry.content == "Existing pinned preference" and entry.pinned and entry.learning == {}
        assert entry.source_conversation_id == cid
        assert db.get(Conversation, cid).personal_memory is True
        assert preferences(db)["learn"] is False
        assert (
            db.execute(text("SELECT memory_id FROM memory_fts WHERE memory_fts MATCH 'pinned'")).scalar_one()
            == mid
        )
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        assert len(list(db.scalars(select(MemoryEntry)))) == 1
