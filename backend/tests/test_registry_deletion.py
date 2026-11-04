"""Removed definitions leave an empty workspace without destroying provenance."""

from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from app.api import app
from app.db import alembic_config, migrate, session_factory, utcnow
from app.models import Agent, Project, Run, Worktree
from app.registry_lifecycle import RegistryDeletedError
from app.runs import create_run as _create_run
from app.runs import create_task as _create_task
from app.schedule import due_agents, launch_agent
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def create_task(session, **kwargs):
    return _create_task(session, prompt="", **kwargs)


def create_run(session, task, **kwargs):
    return _create_run(session, task, run_type="testing", **kwargs)


def agent(api, **kwargs):
    response = api.post(
        "/api/agents",
        json={
            "name": "Neutral report",
            "goal": "Write a neutral report",
            "model": "synthetic-local",
            **kwargs,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def item(row):
    return {"id": row["id"], "expected_updated_at": row["updated_at"]}


def remove(api, kind, *rows):
    return api.post(f"/api/{kind}/delete", json={"confirmed": True, "items": [item(row) for row in rows]})


def test_delete_keeps_history_blocks_enable_and_is_idempotent():
    api = TestClient(app)
    a = agent(api, enabled=True, trigger="interval", interval_seconds=3600)
    with session_factory()() as session:
        task = create_task(session, title="Previous report", capability="testing.fake", agent_id=a["id"])
        run = create_run(session, task, capability="testing.fake", executor_type="fake")
        run.status = "succeeded"
        session.commit()
        rid = run.id
    assert remove(api, "agents", a).json() == {"deleted": 1}
    assert api.get("/api/agents").json() == []
    assert api.get("/api/agents/" + a["id"]).status_code == 410
    assert (
        api.post(
            "/api/agents/" + a["id"] + "/enabled",
            json={"enabled": True, **{k: v for k, v in item(a).items() if k != "id"}},
        ).status_code
        == 410
    )
    assert remove(api, "agents", a).json() == {"deleted": 0}
    assert api.get("/api/runs/" + rid).status_code == 200
    with session_factory()() as session:
        saved = session.get(Agent, a["id"])
        assert saved.deleted_at and not saved.enabled and saved.next_run_at is None
        assert due_agents(session) == []
        with pytest.raises(ValueError, match="deleted"):
            launch_agent(session, saved, triggered_by="manual")


def test_version_active_and_missing_item_fail_entire_batch():
    api = TestClient(app)
    a, b = agent(api), agent(api)
    changed = dict(b, updated_at=(utcnow() - timedelta(days=1)).isoformat())
    assert remove(api, "agents", a, changed).status_code == 409
    missing = dict(b, id=str(uuid4()))
    assert remove(api, "agents", a, missing).status_code == 404
    with session_factory()() as session:
        task = create_task(session, title="Owned work", capability="testing.fake", agent_id=b["id"])
        run = create_run(session, task, capability="testing.fake", executor_type="fake")
        session.commit()
        rid = run.id
    assert remove(api, "agents", a, b).status_code == 409
    assert len(api.get("/api/agents").json()) == 2
    with session_factory()() as session:
        session.get(Run, rid).status = "canceled"
        session.commit()
    assert remove(api, "agents", a, b).json() == {"deleted": 2}


def test_confirmation_and_unique_bounded_selection():
    api = TestClient(app)
    a = agent(api)
    for body in (
        {"confirmed": False, "items": [item(a)]},
        {"items": [item(a)]},
        {"confirmed": True, "items": []},
        {"confirmed": True, "items": [item(a), item(a)]},
        {"confirmed": True, "items": [item(a)] * 201},
    ):
        assert api.post("/api/agents/delete", json=body).status_code == 422
    response = api.request(
        "DELETE", "/api/agents/" + a["id"], json={"confirmed": True, "expected_updated_at": a["updated_at"]}
    )
    assert response.status_code == 204


def test_private_batch_never_deletes_foreign_records(accounts):
    _, alice, bob = accounts
    a, b = agent(alice), agent(bob)
    assert remove(alice, "agents", a, b).status_code == 404
    assert len(alice.get("/api/agents").json()) == 1
    assert remove(bob, "agents", b).status_code == 200
    assert alice.get("/api/agents/" + b["id"]).status_code == 404
    assert remove(alice, "agents", b).status_code == 404
    assert remove(alice, "agents", a).status_code == 200


def test_project_removal_pauses_unlinks_preserves_files_and_worktrees(tmp_path):
    api = TestClient(app)
    repo = tmp_path / "original"
    repo.mkdir()
    marker = repo / "precious.txt"
    marker.write_text("Keep this file")
    with session_factory()() as session:
        project = Project(name="Original", repo_path=str(repo))
        session.add(project)
        session.flush()
        pid = project.id
        project_version = project.updated_at.isoformat()
        # Deliberately persist before leaving the context.
        session.commit()
    a = agent(api, project_id=pid, enabled=True)
    with session_factory()() as session:
        task = create_task(session, title="Prior work", capability="testing.fake", project_id=pid)
        run = create_run(session, task, capability="testing.fake", executor_type="fake")
        run.status = "succeeded"
        session.flush()
        tree = Worktree(project_id=pid, run_id=run.id, branch="ai/old", relative_path="worktrees/old")
        session.add(tree)
        session.commit()
        wid = tree.id
        rid = run.id
    assert remove(api, "projects", {"id": pid, "updated_at": project_version}).json() == {"deleted": 1}
    assert api.get("/api/projects").json() == []
    assert api.get("/api/projects/" + pid).status_code == 410
    saved = api.get("/api/agents/" + a["id"]).json()
    assert saved["project_id"] is None and not saved["enabled"]
    assert marker.read_text() == "Keep this file"
    assert api.get("/api/runs/" + rid).status_code == 200
    with session_factory()() as session:
        assert session.get(Worktree, wid).project_id == pid
        assert session.get(Project, pid).deleted_at


@pytest.mark.parametrize(
    "reference,producer",
    [
        ("agent", "task"),
        ("agent", "run"),
        ("project", "task"),
        ("project", "run"),
        ("project", "agent"),
        ("project", "worktree"),
    ],
)
def test_new_reference_to_removed_definition_is_denied(reference, producer):
    with session_factory()() as session:
        parent = (
            Agent(name="Removed", deleted_at=utcnow())
            if reference == "agent"
            else Project(name="Removed", repo_path="/synthetic", deleted_at=utcnow())
        )
        session.add(parent)
        session.commit()
        ref = {reference + "_id": parent.id}
        task = create_task(session, title="Unrelated", capability="testing.fake")
        session.commit()
        if producer == "worktree":
            run = create_run(session, task, capability="testing.fake", executor_type="fake")
            session.commit()
        with pytest.raises(RegistryDeletedError):
            if producer == "task":
                create_task(session, title="Legacy retry", capability="testing.fake", **ref)
            elif producer == "run":
                create_run(session, task, capability="testing.fake", executor_type="fake", **ref)
            elif producer == "agent":
                session.add(Agent(name="New", **ref))
            else:
                session.add(Worktree(run_id=run.id, branch="ai/new", relative_path="worktrees/new", **ref))
            session.commit()


def test_migration_preserves_registry_and_history():
    with session_factory()() as session:
        p = Project(name="Existing", repo_path="/synthetic")
        session.add(p)
        session.flush()
        a = Agent(name="Existing", project_id=p.id)
        session.add(a)
        session.flush()
        pid, aid = p.id, a.id
        session.commit()
    command.downgrade(alembic_config(), "0042")
    migrate()
    with session_factory()() as session:
        assert session.get(Project, pid).deleted_at is None
        assert session.get(Agent, aid).deleted_at is None
        assert session.get(Agent, aid).project_id == pid
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        session.get(Agent, aid).deleted_at = utcnow()
        session.commit()
    with pytest.raises(RuntimeError, match="resurrecting"):
        command.downgrade(alembic_config(), "0042")


def test_same_transaction_tombstone_cannot_queue_or_reenable():
    with session_factory()() as session:
        agent = Agent(name="Removed", enabled=False)
        session.add(agent)
        session.commit()
        agent.deleted_at = utcnow()
        with pytest.raises(RegistryDeletedError):
            create_task(session, title="Late work", agent_id=agent.id, capability="testing.fake")
        session.rollback()
        agent.deleted_at = utcnow()
        session.commit()
        agent.enabled = True
        with pytest.raises(RegistryDeletedError):
            session.commit()


def test_fixed_expiry_can_keep_own_housekeeping_after_project_removal():
    with session_factory()() as session:
        project = Project(name="Removed", repo_path="/synthetic", deleted_at=utcnow())
        session.add(project)
        session.commit()
        task = create_task(
            session, title="Owned expiry", project_id=project.id, capability="coding.worktree.remove"
        )
        run = create_run(session, task, capability="coding.worktree.remove", executor_type="worktree_remove")
        session.commit()
        assert run.project_id == project.id


def test_cached_parent_from_previous_transaction_cannot_bypass_deletion():
    with session_factory()() as stale:
        agent = Agent(name="Previously loaded", enabled=False)
        stale.add(agent)
        stale.commit()
        aid = agent.id
        with session_factory()() as deleting:
            deleting.get(Agent, aid).deleted_at = utcnow()
            deleting.commit()
        assert agent.deleted_at is None  # expire_on_commit=False retains this cache.
        with pytest.raises(RegistryDeletedError):
            create_task(stale, title="Late cached retry", agent_id=aid, capability="testing.fake")
