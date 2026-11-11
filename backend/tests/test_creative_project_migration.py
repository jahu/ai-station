from uuid import uuid4

from alembic import command
from app.db import alembic_config, control_session_factory, migrate, reset_engine
from app.models import CreativeSession, CreativeTurn, TimelineRevision
from app.runs import create_run, create_task
from sqlalchemy import text


def test_project_migration_preserves_populated_sessions_turns_and_timeline():
    with control_session_factory()() as session:
        task = create_task(session, title="Keep task", prompt="Keep prompt", capability="timeline")
        run = create_run(session, task, run_type="media", capability="timeline", executor_type="fake")
        workspace = CreativeSession(capability="timeline", title="Keep workspace", draft={"revision": 3})
        session.add(workspace)
        session.flush()
        turn = CreativeTurn(
            session_id=workspace.id,
            task_id=task.id,
            run_id=run.id,
            client_request_id=str(uuid4()),
            request_sha256="a" * 64,
            position=1,
            feedback="Keep feedback",
            request_parameters={"manifest": "original"},
        )
        revision = TimelineRevision(
            session_id=workspace.id,
            client_request_id=str(uuid4()),
            request_sha256="b" * 64,
            position=1,
            manifest={"clips": ["retained"]},
            sources={"retained": {"sha256": "c" * 64}},
        )
        session.add_all([turn, revision])
        session.commit()
        wid, tid, rid = workspace.id, turn.id, revision.id
    # No creative projects exist yet; the lossless downgrade retains the populated
    # 0045 history and lets the forward migration run against a committed old DB.
    reset_engine()
    command.downgrade(alembic_config(), "0045")
    migrate()
    with control_session_factory()() as session:
        workspace = session.get(CreativeSession, wid)
        assert workspace.title == "Keep workspace" and workspace.draft == {"revision": 3}
        assert workspace.creative_project_id is None
        assert session.get(CreativeTurn, tid).feedback == "Keep feedback"
        assert session.get(TimelineRevision, rid).manifest == {"clips": ["retained"]}
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
