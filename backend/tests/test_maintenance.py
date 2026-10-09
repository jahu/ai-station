from pathlib import Path

from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run, Task
from app.permissions import ALL_PERMISSIONS
from app.recovery import recover_stale
from app.runs import create_run, create_task, request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


def drain(session, worker="backup-test", limit=10):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def test_upgrade_readiness_is_inspect_only_and_restore_stays_unpublished():
    client = TestClient(app)
    body = client.get("/api/maintenance").json()
    assert body["schema_current_matches_head"] is True
    assert body["schema_head"] == "0019"
    assert body["restore"] == "unpublished"
    assert body["image_rollout"] == "unpublished"
    assert body["lan_bind_allowed"] is False
    assert body["data_survives_compose_down"] is True
    assert body["compose_down_removes_bind_data"] is False
    assert body["application_data"] == "bind-mount"
    assert body["last_backup"] is None
    assert body["interrupted_runs"] == []
    assert client.post("/api/maintenance/restore", json={}).status_code == 404
    assert client.post("/api/maintenance/rollout", json={}).status_code == 404
    assert "manage_station" in ALL_PERMISSIONS


def test_backup_run_integrity_checks_and_never_restores():
    client = TestClient(app)
    queued = client.post("/api/maintenance/backups", json={})
    assert queued.status_code == 202
    run = queued.json()
    assert run["executor_type"] == "sqlite_backup"
    assert run["effective_permissions"] == ["manage_station"]
    assert run["retry_class"] == "inspect"
    with session_factory()() as session:
        drain(session)
        row = session.get(Run, run["id"])
        assert row.status == "succeeded", f"{row.error_type}: {row.error_message}"
        assert "integrity_check=ok" in row.summary
        names = sorted(session.scalars(select(Artifact.original_filename).where(Artifact.run_id == row.id)))
        assert names == ["ai-station.sqlite", "backup-report.json"]
        sqlite = session.scalars(
            select(Artifact).where(
                Artifact.run_id == row.id, Artifact.original_filename == "ai-station.sqlite"
            )
        ).one()
        assert sqlite.relative_path == f"backups/{row.id}.sqlite"
        stored = get_settings().data_dir / sqlite.relative_path
        assert stored.is_file() and sqlite.sha256 and sqlite.size_bytes == stored.stat().st_size
    listed = client.get("/api/maintenance/backups").json()
    assert listed["restore"] == "unpublished"
    assert listed["items"][0]["id"] == run["id"]
    assert listed["items"][0]["restore"] == "unpublished"
    ready = client.get("/api/maintenance").json()
    assert ready["last_backup"]["id"] == run["id"]
    assert ready["restore"] == "unpublished"
    assert client.post("/api/maintenance/backups", json={}).status_code == 202
    assert client.post("/api/maintenance/restore", json={"run_id": run["id"]}).status_code == 404


def test_backup_cancel_and_missing_permission_fail_closed():
    client = TestClient(app)
    run = client.post("/api/maintenance/backups", json={}).json()
    canceled = client.post(f"/api/runs/{run['id']}/cancel").json()
    assert canceled["status"] == "canceled"
    with session_factory()() as session:
        task = create_task(session, title="no-perm", prompt="", capability="station.backup")
        unauthorized = create_run(
            session,
            task,
            run_type="maintenance",
            capability="station.backup",
            executor_type="sqlite_backup",
            permissions=[],
            retry_class="inspect",
        )
        session.commit()
        drain(session)
        failed = session.get(Run, unauthorized.id)
        assert failed.status == "failed"
        assert failed.error_type == "PermissionDenied"
        assert session.get(Task, task.id) is not None


def test_cancel_after_copy_deletes_partial_backup(monkeypatch):
    from app import maintenance

    client = TestClient(app)
    queued = client.post("/api/maintenance/backups", json={}).json()
    real_copy = maintenance.copy_database

    def copy_and_cancel(source: Path, destination: Path) -> None:
        real_copy(source, destination)
        with session_factory()() as session:
            request_cancel(session, session.get(Run, queued["id"]))
            session.commit()

    monkeypatch.setattr(maintenance, "copy_database", copy_and_cancel)
    with session_factory()() as session:
        drain(session)
        row = session.get(Run, queued["id"])
        assert row.status == "canceled", f"{row.error_type}: {row.error_message}"
        leftover = get_settings().data_dir / f"backups/{row.id}.sqlite"
        assert not leftover.exists()
        assert session.scalar(select(Artifact.id).where(Artifact.run_id == row.id)) is None


def test_second_backup_conflicts_while_active():
    client = TestClient(app)
    first = client.post("/api/maintenance/backups", json={})
    assert first.status_code == 202
    conflict = client.post("/api/maintenance/backups", json={})
    assert conflict.status_code == 409


def test_acknowledge_interrupted_does_not_replay_or_restore():
    client = TestClient(app)
    with session_factory()() as session:
        task = create_task(session, title="Interrupted photo", prompt="", capability="image.generate")
        run = create_run(
            session,
            task,
            run_type="image",
            capability="image.generate",
            executor_type="photo_pipe",
            retry_class="inspect",
        )
        run.status = "interrupted"
        run.finished_at = utcnow()
        session.commit()
        run_id = run.id
    ready = client.get("/api/maintenance").json()
    assert ready["interrupted_runs"][0]["id"] == run_id
    assert ready["interrupted_runs"][0]["replay"] is False
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["interrupted_runs"][0]["id"] == run_id
    acknowledged = client.post(f"/api/maintenance/interrupted/{run_id}/acknowledge", json={})
    assert acknowledged.status_code == 200
    body = acknowledged.json()
    assert body["status"] == "interrupted"
    assert body["replay"] is False
    assert body["restore"] == "unpublished"
    with session_factory()() as session:
        row = session.get(Run, run_id)
        assert row.status == "interrupted"
        assert row.metadata_json["inspection_acknowledged_at"]
    assert client.get("/api/maintenance").json()["interrupted_runs"] == []
    assert client.get("/api/dashboard").json()["interrupted_runs"] == []
    assert client.post(f"/api/maintenance/interrupted/{run_id}/acknowledge", json={}).status_code == 200
    backup = client.post("/api/maintenance/backups", json={}).json()
    with session_factory()() as session:
        drain(session)
        recover_stale(session)
        assert session.get(Run, run_id).status == "interrupted"
        copied = session.get(Run, backup["id"])
        assert copied.status == "succeeded", f"{copied.error_type}: {copied.error_message}"
    assert client.post("/api/maintenance/restore", json={"run_id": backup["id"]}).status_code == 404
    assert client.post(f"/api/runs/{run_id}/retry-workflow", json={}).status_code in {404, 409}


def test_acknowledge_rejects_active_runs():
    client = TestClient(app)
    with session_factory()() as session:
        task = create_task(session, title="live", prompt="", capability="test")
        run = create_run(session, task, run_type="test", capability="test", executor_type="fake")
        session.commit()
        run_id = run.id
    assert client.post(f"/api/maintenance/interrupted/{run_id}/acknowledge", json={}).status_code == 409
