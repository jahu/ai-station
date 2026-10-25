"""Disposable-only permanent deletion, approval, stale scopes and recovery."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.api import app
from app.artifact_purge import ArtifactPurgeExecutor
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run
from app.recovery import recover_stale
from app.runs import claim_next, request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from test_library import upload


def test_tampered_scope_cannot_reuse_an_approval():
    with TestClient(app) as client:
        first = upload(client)
        other = upload(client)
        run = prepare(client, [first]).json()
        grant(client, run)
        with session_factory()() as session:
            record = session.get(Run, run["id"])
            record.parameters = {
                **record.parameters,
                "items": [{**record.parameters["items"][0], "id": other["id"]}],
            }
            session.commit()
        work()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        for row in [first, other]:
            assert client.get(f"/api/artifacts/{row['id']}/file").status_code == 200


def test_cancel_after_claim_has_no_filesystem_side_effect():
    with TestClient(app) as client:
        row = upload(client)
        run = prepare(client, [row]).json()
        grant(client, run)
        with session_factory()() as session:
            claimed = claim_next(session, "cancel-worker")
            request_cancel(session, claimed)
            session.commit()
            ArtifactPurgeExecutor().execute(session, claimed)
            session.commit()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
        assert client.get(f"/api/artifacts/{row['id']}/file").status_code == 200


def prepare(client, artifacts=None, *, scope="selected", request_id=None):
    return client.post(
        "/api/library/purges",
        json={
            "request_id": request_id or str(uuid4()),
            "scope": scope,
            "items": [
                {"id": row["id"], "expected_updated_at": row["library_updated_at"]} for row in artifacts or []
            ],
        },
    )


def grant(client, run):
    response = client.post(f"/api/runs/{run['id']}/approval", json={"resolution": "granted"})
    assert response.status_code == 200, response.text


def work():
    with session_factory()() as session:
        tick(session, "purge-test")


def test_approval_idempotency_direct_delete_preserves_provenance():
    with TestClient(app) as client:
        source = upload(client)
        other = upload(client)
        path = get_settings().data_dir / source["relative_path"]
        thumbnail = get_settings().data_dir / source["thumbnail_relative_path"]
        request_id = str(uuid4())
        response = prepare(client, [source], request_id=request_id)
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["status"] == "waiting_for_approval"
        assert prepare(client, [source], request_id=request_id).json()["id"] == run["id"]
        assert prepare(client, [other], request_id=request_id).status_code == 409
        work()
        assert path.is_file()  # Waiting for a product confirmation is never execution.
        grant(client, run)
        work()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
        assert not path.exists() and not thumbnail.exists()
        assert client.get(f"/api/artifacts/{source['id']}/file").status_code == 410
        assert client.get(f"/api/artifacts/{source['id']}/thumbnail").status_code == 410
        tombstone = client.get(f"/api/artifacts/{source['id']}").json()
        assert tombstone["purged_at"] and tombstone["purge_run_id"] == run["id"]
        assert [row["id"] for row in client.get("/api/artifacts").json()] == [other["id"]]
        assert client.get("/api/artifacts?view=trash").json() == []
        assert (
            client.post(
                f"/api/artifacts/{source['id']}/restore",
                json={"expected_updated_at": tombstone["library_updated_at"]},
            ).status_code
            == 409
        )
        events = client.get(f"/api/runs/{run['id']}/events").json()
        assert any(row["event_type"] == "artifact.purge_completed" for row in events)


def test_empty_trash_freezes_every_page_and_excludes_new_trash():
    with TestClient(app) as client:
        originals = [upload(client, f"source-{i}.png") for i in range(3)]
        for row in originals:
            client.request("DELETE", f"/api/artifacts/{row['id']}", json={"expected_updated_at": None})
        assert client.get("/api/library/trash-count").json() == {"count": 3}
        assert len(client.get("/api/artifacts?view=trash&limit=1").json()) == 1
        run = prepare(client, scope="trash").json()
        assert run["approval"]["payload"]["count"] == 3
        late = upload(client, "newly-trashed.png")
        client.request("DELETE", f"/api/artifacts/{late['id']}", json={"expected_updated_at": None})
        grant(client, run)
        work()
        assert client.get("/api/library/trash-count").json() == {"count": 1}
        assert client.get(f"/api/artifacts/{late['id']}/file").status_code == 200


def test_changed_confirmation_and_denied_approval_never_unlink():
    with TestClient(app) as client:
        row = upload(client)
        run = prepare(client, [row]).json()
        client.patch(f"/api/artifacts/{row['id']}", json={"expected_updated_at": None, "title": "changed"})
        grant(client, run)
        work()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        assert client.get(f"/api/artifacts/{row['id']}/file").status_code == 200
        changed = client.get(f"/api/artifacts/{row['id']}").json()
        denied = prepare(client, [changed]).json()
        client.post(f"/api/runs/{denied['id']}/approval", json={"resolution": "denied"})
        work()
        assert client.get(f"/api/artifacts/{row['id']}/file").status_code == 200


@pytest.mark.parametrize("attack", ["file_symlink", "directory_symlink", "bytes", "outside"])
def test_unsafe_path_or_replaced_bytes_are_retained(tmp_path, attack):
    with TestClient(app) as client:
        row = upload(client)
        path = get_settings().data_dir / row["relative_path"]
        outside = tmp_path / "precious.txt"
        outside.write_text("never remove")
        if attack == "outside":
            with session_factory()() as session:
                session.get(Artifact, row["id"]).relative_path = "logs/precious.txt"
                session.commit()
            row = client.get(f"/api/artifacts/{row['id']}").json()
        run = prepare(client, [row]).json()
        if attack == "file_symlink":
            path.unlink()
            path.symlink_to(outside)
        elif attack == "directory_symlink":
            moved = tmp_path / "moved"
            path.parent.rename(moved)
            path.parent.symlink_to(moved, target_is_directory=True)
        elif attack == "bytes":
            path.write_bytes(b"changed content")
        grant(client, run)
        work()
        result = client.get(f"/api/runs/{run['id']}").json()
        assert result["status"] == "failed", result
        assert outside.read_text() == "never remove"
        assert not client.get(f"/api/artifacts/{row['id']}").json().get("purged_at")
        assert path.exists() or path.is_symlink()


def test_shared_file_and_derived_lineage_remain_available():
    with TestClient(app) as client:
        row = upload(client)
        child = upload(client)
        shared = upload(client)
        with session_factory()() as session:
            original = session.get(Artifact, row["id"])
            session.get(Artifact, shared["id"]).relative_path = original.relative_path
            session.get(Artifact, child["id"]).parent_artifact_ids = [original.id]
            session.commit()
        run = prepare(client, [row]).json()
        grant(client, run)
        work()
        assert client.get(f"/api/artifacts/{shared['id']}/file").status_code == 200
        lineage = client.get(f"/api/artifacts/{child['id']}/lineage").json()
        assert lineage["sources"][0]["purged_at"]
        assert client.get(f"/api/artifacts/{row['id']}/file").status_code == 410


def test_partial_failure_retry_and_stop_do_not_broaden_selection(monkeypatch):
    from app import artifact_purge

    with TestClient(app) as client:
        originals = [upload(client, f"source-{i}.png") for i in range(2)]
        run = prepare(client, originals).json()
        grant(client, run)
        unlink = artifact_purge._unlink_owned

        def fail_one(path, **kwargs):
            if path == originals[1]["relative_path"]:
                raise OSError("Test disk error")
            return unlink(path, **kwargs)

        monkeypatch.setattr(artifact_purge, "_unlink_owned", fail_one)
        work()
        assert client.get(f"/api/artifacts/{originals[0]['id']}").json()["purged_at"]
        remaining = client.get(f"/api/artifacts/{originals[1]['id']}").json()
        retry = prepare(client, [remaining]).json()
        grant(client, retry)
        monkeypatch.setattr(artifact_purge, "_unlink_owned", unlink)
        work()
        assert client.get(f"/api/runs/{retry['id']}").json()["status"] == "succeeded"


def test_recovery_resumes_committed_intent_without_replaying_other_work(monkeypatch):

    with TestClient(app) as client:
        row = upload(client)
        run = prepare(client, [row]).json()
        grant(client, run)
        with session_factory()() as session:
            claimed = claim_next(session, "dead-worker")
            transition(session, claimed, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, claimed, RunStatus.RUNNING, event_type="executor.started")
            source = session.get(Artifact, row["id"])
            source.purge_run_id = claimed.id
            claimed.lease_expires_at = utcnow() - timedelta(seconds=30)
            session.commit()
            Path(get_settings().data_dir / row["relative_path"]).unlink()
            assert recover_stale(session) == [claimed.id]
            session.commit()
        work()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"


def test_stop_between_items_leaves_remaining_files(monkeypatch):
    with TestClient(app) as client:
        rows = [upload(client, f"source-{i}.png") for i in range(2)]
        run = prepare(client, rows).json()
        grant(client, run)
        remove = ArtifactPurgeExecutor._remove_item

        def remove_then_stop(self, session, executing, item):
            result = remove(self, session, executing, item)
            request_cancel(session, executing)
            session.commit()
            return result

        monkeypatch.setattr(ArtifactPurgeExecutor, "_remove_item", remove_then_stop)
        work()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
        assert client.get(f"/api/artifacts/{rows[0]['id']}/file").status_code == 410
        assert client.get(f"/api/artifacts/{rows[1]['id']}/file").status_code == 200
