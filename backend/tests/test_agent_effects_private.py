"""Same real account policy as all agent/media entry points."""

from app.artifacts import register_file
from app.config import get_settings
from app.data_access import DataScope, ScopedSession
from app.db import get_engine
from app.runs import create_run, create_task, transition
from app.state import RunStatus
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_effects import sound_bridge as sound_bridge


def test_effects_agent_cannot_use_another_accounts_film(accounts, sound_bridge):
    admin, alice, bob = accounts
    owner = alice.get("/api/auth").json()["user"]["id"]
    path = get_settings().data_dir / "source-film.mp4"
    path.write_bytes(b"synthetic private film fixture")
    with ScopedSession(bind=get_engine(), scope=DataScope(user_id=owner)) as db:
        task = create_task(db, title="Private film", prompt="", capability="qa.fixture")
        run = create_run(db, task, run_type="video", capability="qa.fixture", executor_type="wan_video")
        for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED):
            transition(db, run, state, event_type="qa.fixture", payload={})
        source = register_file(
            db,
            source=path,
            artifact_type="video",
            mime_type="video/mp4",
            original_filename="Private film.mp4",
            run_id=run.id,
            metadata={"frames": 33, "fps": 24, "width": 1280, "height": 704},
        )
        db.commit()
        aid = source.id
    definition = {
        "name": "Film atmosphere",
        "goal": "Describe the film sounds",
        "tools": ["create_media"],
        "enabled": True,
        "media": {"kind": "effects", "request": {"video_artifact_id": aid, "prompt": "Wind in trees"}},
    }
    created = alice.post("/api/agents", json=definition)
    assert created.status_code == 201, created.text
    identity = created.json()["id"]
    denied = bob.post("/api/agents", json=definition)
    assert denied.status_code == 409, denied.text
    assert bob.get("/api/agents/" + identity).status_code == 404
    assert admin.get("/api/agents/" + identity).status_code == 404
    assert (
        admin.get("/api/agents/" + identity, headers={"x-ai-station-inspect-all": "true"}).status_code == 200
    )
    assert bob.get("/api/artifacts/" + aid + "/file").status_code == 404
