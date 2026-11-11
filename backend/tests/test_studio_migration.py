import pytest
from alembic import command
from app.db import alembic_config, control_session_factory, migrate, reset_engine
from app.models import CreativeProject, CreativeSession, StudioMaterial
from sqlalchemy import text


def test_studio_migration_adds_empty_collections_without_rewriting_existing_creative_work():
    with control_session_factory()() as session:
        project = CreativeProject(name="Preserved identity", identity={"colors": ["#123456"]})
        session.add(project)
        session.flush()
        saved = CreativeSession(
            capability="images",
            title="Preserved workspace",
            draft={"keep": "source"},
            creative_project_id=project.id,
        )
        session.add(saved)
        session.commit()
        pid, sid = project.id, saved.id
    reset_engine()
    command.downgrade(alembic_config(), "0046")
    migrate()
    with control_session_factory()() as session:
        assert session.get(CreativeProject, pid).identity == {"colors": ["#123456"]}
        assert session.get(CreativeSession, sid).draft == {"keep": "source"}
        assert session.get(CreativeSession, sid).creative_project_id == pid
        assert session.scalar(text("SELECT count(*) FROM studio_materials")) == 0
        assert session.scalar(text("SELECT count(*) FROM studio_revisions")) == 0
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_populated_materials_cannot_be_discarded_by_downgrade():
    with control_session_factory()() as session:
        row = StudioMaterial(
            title="Keep this material",
            brief="Keep the original brief",
            options={"audio": "silent"},
            request_sha256="a" * 64,
        )
        session.add(row)
        session.commit()
        identity = row.id
    reset_engine()
    with pytest.raises(RuntimeError, match="reviewed backup"):
        command.downgrade(alembic_config(), "0046")
    with control_session_factory()() as session:
        assert session.get(StudioMaterial, identity).brief == "Keep the original brief"
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0047"
