"""Administrator-only full-station backups retain account and worker boundaries."""

import stat

import pytest
from app import maintenance
from app.accounts import authenticate_cookies
from app.config import clear_settings_cache, get_settings
from app.data_access import data_session_for
from app.db import control_session_factory
from app.engine import tick
from app.models import Artifact, Run, User
from app.runs import create_run, create_task
from sqlalchemy import select
from test_account_private_access import second_admin
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def work():
    with control_session_factory()() as queue:
        return tick(queue, "account-backup-worker")


def backup(owner):
    response = owner.post("/api/maintenance/backups", json={})
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    assert work() == identity
    response = owner.get("/api/runs/" + identity)
    assert response.json()["status"] == "succeeded", response.text
    items = owner.get("/api/maintenance/backups").json()["items"]
    item = next(row for row in items if row["id"] == identity)
    artifact = next(row for row in item["artifacts"] if row["filename"] == "ai-station.sqlite")
    return identity, artifact["id"]


def test_administrator_readiness_and_real_worker_backup_are_usable(accounts, monkeypatch):
    owner, alice, _ = accounts
    foreign = alice.post("/api/testing/runs", json={})
    assert foreign.status_code == 202
    # Keep another owner's job queued: readiness reports the shared activity
    # count without revealing that Run in the administrator's private list.
    response = owner.get("/api/maintenance")
    assert response.status_code == 200, response.text
    assert response.json()["schema_current_matches_head"]
    assert response.json()["journal_mode"] == "wal"
    assert response.json()["active_runs"] == 1
    assert owner.get("/api/runs").json() == []
    assert work() == foreign.json()["id"]
    monkeypatch.setenv("AI_STATION_LAN_HOST", "192.168.20.5")
    clear_settings_cache()
    assert owner.get("/api/maintenance").json()["lan_bind_allowed"]
    identity, artifact = backup(owner)
    assert owner.get("/api/artifacts/" + artifact + "/file").content.startswith(b"SQLite format 3")
    inspected = owner.get("/api/maintenance/backups/" + identity)
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["integrity_check"] == "ok" and inspected.json()["hash_matches"]
    assert owner.get("/api/maintenance").json()["last_backup"]["id"] == identity
    path = get_settings().data_dir / "backups" / (identity + ".sqlite")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for route in ("/api/maintenance", "/api/maintenance/backups", "/api/maintenance/backups/" + identity):
        assert alice.get(route).status_code == 403
    assert alice.post("/api/maintenance/backups", json={}).status_code == 403
    assert alice.get("/api/artifacts/" + artifact + "/file").status_code == 404


def test_demotion_hides_an_owned_backup_from_files_lists_inputs_and_cached_gets(accounts, private_app):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    identity, artifact = backup(owner)
    with control_session_factory()() as auth:
        principal = authenticate_cookies(auth, dict(owner.cookies))
    with data_session_for(principal) as cached:
        assert cached.get(Artifact, artifact) is not None
        cached.commit()
        demoted = other.patch(
            "/api/admin/users/" + principal.user_id, json={"enabled": True, "is_admin": False}
        )
        assert demoted.status_code == 200, demoted.text
        assert cached.get(Artifact, artifact) is None
    # Signing back in as an ordinary member must not reveal the full database,
    # even though this account originally owned its backup Run.
    from test_account_private_api import PASSWORD

    assert owner.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD}).status_code == 200
    assert owner.get("/api/artifacts/" + artifact).status_code == 404
    assert owner.get("/api/artifacts/" + artifact + "/file").status_code == 404
    assert not any(row["id"] == artifact for row in owner.get("/api/artifacts").json())
    from app.data_access import DataScope, ScopedSession
    from app.db import get_engine

    with ScopedSession(bind=get_engine(), scope=DataScope(principal.user_id, execution=True)) as session:
        assert session.get(Artifact, artifact) is None
        assert not session.scalars(select(Artifact).where(Artifact.run_id == identity)).all()


@pytest.mark.parametrize("when", ["before_dispatch", "during_copy"])
def test_role_changes_prevent_backup_publication(accounts, private_app, monkeypatch, when):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    owner_id = owner.get("/api/auth").json()["user"]["id"]
    response = owner.post("/api/maintenance/backups", json={})
    assert response.status_code == 202
    identity = response.json()["id"]

    def demote():
        assert (
            other.patch("/api/admin/users/" + owner_id, json={"enabled": True, "is_admin": False}).status_code
            == 200
        )

    copied = []
    original = maintenance.copy_database

    def copy(source, destination):
        copied.append(True)
        original(source, destination)
        demote()

    if when == "before_dispatch":
        demote()
    else:
        monkeypatch.setattr(maintenance, "copy_database", copy)
    assert work() == (None if when == "before_dispatch" else identity)
    with control_session_factory()() as queue:
        run = queue.get(Run, identity)
        assert run.status == "canceled", run.error_message
        assert not queue.get(User, owner_id).is_admin
        assert queue.scalar(select(Artifact.id).where(Artifact.run_id == identity)) is None
    assert copied == ([] if when == "before_dispatch" else [True])
    assert not (get_settings().data_dir / "backups" / (identity + ".sqlite")).exists()


def test_permission_alone_does_not_allow_a_member_to_run_station_backup(accounts):
    _, alice, _ = accounts
    identity = alice.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as queue:
        task = create_task(queue, title="Untrusted backup", prompt="", capability="station.backup")
        task.owner_id = identity
        run = create_run(
            queue,
            task,
            run_type="maintenance",
            capability="station.backup",
            executor_type="sqlite_backup",
            permissions=["manage_station"],
        )
        run.owner_id = identity
        queue.commit()
        run_id = run.id
    assert work() == run_id
    with control_session_factory()() as queue:
        assert queue.get(Run, run_id).status == "failed"
        assert not queue.scalars(select(Artifact).where(Artifact.run_id == run_id)).all()
