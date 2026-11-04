"""Ownership backfill preserves primary IDs, children, FTS and artifact bytes."""

from uuid import uuid4

import pytest
from alembic import command
from app import models as m
from app.config import get_settings
from app.db import alembic_config, migrate, reset_engine, session_factory
from sqlalchemy import inspect, text

ROOTS = (
    m.Task,
    m.Run,
    m.Artifact,
    m.Conversation,
    m.Project,
    m.Agent,
    m.Approval,
    m.MemoryEntry,
    m.Connector,
    m.ChatProvider,
)


def old_identity_schema():
    reset_engine()
    command.downgrade(alembic_config(), "0037")


def test_all_existing_private_roots_are_backfilled_without_rebuilding_children_or_files():
    old_identity_schema()
    ids = {model: str(uuid4()) for model in ROOTS}
    values = {
        m.Conversation: {"title": "Synthetic conversation"},
        m.Project: {"name": "Synthetic project", "repo_path": "/synthetic/project"},
        m.Agent: {"name": "Synthetic agent"},
        m.Task: {"title": "Synthetic task", "conversation_id": ids[m.Conversation]},
        m.Run: {"task_id": ids[m.Task], "conversation_id": ids[m.Conversation]},
        m.Artifact: {"artifact_type": "text", "relative_path": "artifacts/legacy.txt", "run_id": ids[m.Run]},
        m.Approval: {"action": "synthetic.action", "run_id": ids[m.Run]},
        m.MemoryEntry: {"scope": "global", "content": "Synthetic legacy memory"},
        m.Connector: {"key": "synthetic-connector", "name": "Synthetic connector"},
        m.ChatProvider: {"key": "synthetic-provider", "name": "Synthetic provider"},
    }
    with session_factory()() as session:
        owner = session.query(m.User).one().id
        for model in (
            m.Conversation,
            m.Project,
            m.Agent,
            m.Task,
            m.Run,
            m.Artifact,
            m.Approval,
            m.MemoryEntry,
            m.Connector,
            m.ChatProvider,
        ):
            session.execute(model.__table__.insert().values(id=ids[model], **values[model]))
        session.execute(
            m.Message.__table__.insert().values(
                id=str(uuid4()),
                conversation_id=ids[m.Conversation],
                role="user",
                content="Synthetic prompt",
            )
        )
        session.execute(
            m.RunEvent.__table__.insert().values(
                id=str(uuid4()),
                run_id=ids[m.Run],
                sequence=1,
                event_type="synthetic.event",
                payload={"retained": True},
            )
        )
        session.execute(
            text(
                "INSERT INTO memory_fts(memory_id, content, tags) VALUES (:id, 'Synthetic legacy memory', '')"
            ),
            {"id": ids[m.MemoryEntry]},
        )
        session.execute(
            m.EmailDelivery.__table__.insert().values(
                id=str(uuid4()),
                connector_id=ids[m.Connector],
                run_id=ids[m.Run],
                payload={"synthetic": "preserved"},
                payload_hash="a" * 64,
                message_id="synthetic-message-id",
            )
        )
        session.commit()
    path = get_settings().data_dir / "artifacts/legacy.txt"
    path.write_bytes(b"Synthetic unchanged artifact bytes")
    migrate()
    migrate()
    with session_factory()() as session:
        for model in ROOTS:
            assert session.get(model, ids[model]).owner_id == owner
        assert session.query(m.Message).one().content == "Synthetic prompt"
        assert session.query(m.RunEvent).one().payload == {"retained": True}
        delivery = session.query(m.EmailDelivery).one()
        assert delivery.connector_id == ids[m.Connector] and delivery.payload == {"synthetic": "preserved"}
        assert (
            session.execute(
                text("SELECT memory_id FROM memory_fts WHERE memory_fts MATCH 'legacy'")
            ).scalar_one()
            == ids[m.MemoryEntry]
        )
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        for model in ROOTS:
            foreign_keys = inspect(session.connection()).get_foreign_keys(model.__tablename__)
            assert any(
                key["constrained_columns"] == ["owner_id"] and key["referred_table"] == "users"
                for key in foreign_keys
            )
    assert path.read_bytes() == b"Synthetic unchanged artifact bytes"


def test_migration_cannot_guess_ownership_after_multiple_accounts_already_exist():
    old_identity_schema()
    with session_factory()() as session:
        session.add(m.User(username="Other", normalized_username="other"))
        session.commit()
    with pytest.raises(RuntimeError, match="Assign private data owners explicitly"):
        migrate()
    with session_factory()() as session:
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0037"


def test_used_private_data_prevents_destructive_downgrade():
    with session_factory()() as session:
        owner = session.query(m.User).one().id
        session.add(m.Task(title="Retain this task", owner_id=owner))
        session.commit()
    with pytest.raises(RuntimeError, match="Private ownership cannot be discarded"):
        command.downgrade(alembic_config(), "0037")
    with session_factory()() as session:
        assert session.query(m.Task).one().owner_id == owner
