from uuid import uuid4

from alembic import command
from app.db import alembic_config
from app.models import CreativeSession, CreativeTurn
from app.runs import create_run, create_task
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session


def test_effects_migration_preserves_legacy_sessions_turns_and_foreign_keys(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.sqlite"))

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "0039")
        with Session(bind=connection) as db:
            task = create_task(db, title="Retained", prompt="Retained prompt", capability="image.generate")
            run = create_run(db, task, run_type="image", capability="image.generate", executor_type="fake")
            workspace = CreativeSession(
                capability="images", title="Before upgrade", draft={"formState": {"prompt": "Keep this"}}
            )
            db.add(workspace)
            db.flush()
            turn = CreativeTurn(
                session_id=workspace.id,
                task_id=task.id,
                run_id=run.id,
                client_request_id=str(uuid4()),
                request_sha256="a" * 64,
                position=1,
                feedback="Keep feedback",
                request_parameters={"prompt": "Original"},
            )
            db.add(turn)
            db.flush()
            wid, tid, rid, task_id = workspace.id, turn.id, run.id, task.id
    # Commit the old database first: this exercises SQLite's real deferred-DROP
    # bookkeeping with populated referencing rows, not merely a fresh schema.
    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with Session(engine) as db:
        workspace = db.get(CreativeSession, wid)
        turn = db.get(CreativeTurn, tid)
        assert workspace.title == "Before upgrade" and workspace.draft == {
            "formState": {"prompt": "Keep this"}
        }
        assert turn.feedback == "Keep feedback" and turn.request_parameters == {"prompt": "Original"}
        assert (turn.session_id, turn.run_id, turn.task_id) == (wid, rid, task_id)
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        db.add(CreativeSession(capability="effects", title="New sound"))
        db.commit()
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0040"
    engine.dispose()
