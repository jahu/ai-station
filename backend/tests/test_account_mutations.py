"""Private workspace mutations retain optimistic versions and owner boundaries."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from app.data_access import DataAccessError, DataScope, ScopedSession, private_for_update
from app.db import control_session_factory, get_engine, utcnow
from app.engine import tick
from app.models import Artifact
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_artifact_purge import grant, prepare
from test_library import upload


def test_library_edit_trash_restore_are_private_and_reject_stale_versions(accounts):
    _, alice, bob = accounts
    own, other = upload(alice), upload(bob)
    path = "/api/artifacts/" + own["id"]
    original = alice.get(path + "/file").content
    edit = {
        "title": "Synthetic private title",
        "notes": "Synthetic private note",
        "expected_updated_at": None,
    }
    changed = alice.patch(path, json=edit)
    assert changed.status_code == 200, changed.text
    assert alice.patch(path, json=edit).status_code == 409
    assert alice.patch("/api/artifacts/" + other["id"], json=edit).status_code == 404
    assert bob.get(path).status_code == 404
    trashed = alice.request(
        "DELETE", path, json={"expected_updated_at": changed.json()["library_updated_at"]}
    )
    assert trashed.status_code == 200, trashed.text
    assert not alice.get("/api/artifacts").json()
    assert [a["id"] for a in alice.get("/api/artifacts?view=trash").json()] == [own["id"]]
    restored = alice.post(
        path + "/restore", json={"expected_updated_at": trashed.json()["library_updated_at"]}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["title"] == edit["title"] and restored.json()["trashed_at"] is None
    assert alice.get(path + "/file").content == original
    assert bob.get("/api/artifacts/" + other["id"]).json()["title"] == ""


def test_archive_restore_and_context_selection_keep_private_versions(accounts):
    _, alice, bob = accounts
    own = alice.post("/api/chat/conversations", json={"model": "synthetic-local"}).json()
    other = bob.post("/api/chat/conversations", json={"model": "synthetic-local"}).json()
    path = "/api/chat/conversations/" + own["id"]
    version = own["settings_version"]
    archived = alice.put(path + "/archive", json={"archived": True, "expected_settings_version": version})
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert (
        alice.put(
            path + "/archive", json={"archived": False, "expected_settings_version": version}
        ).status_code
        == 409
    )
    assert (
        alice.put(
            "/api/chat/conversations/" + other["id"] + "/archive",
            json={"archived": True, "expected_settings_version": version},
        ).status_code
        == 404
    )
    restored = alice.put(
        path + "/archive",
        json={"archived": False, "expected_settings_version": archived.json()["settings_version"]},
    )
    assert restored.status_code == 200, restored.text
    selected = alice.put(
        path + "/work-context",
        json={"task_id": None, "expected_settings_version": restored.json()["settings_version"]},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["settings_version"] == restored.json()["settings_version"] + 1
    assert bob.get("/api/chat/conversations/" + own["id"]).status_code == 404


def test_approved_permanent_deletion_executes_only_for_its_owner(accounts):
    _, alice, bob = accounts
    own, other = upload(alice), upload(bob)
    response = prepare(alice, [own])
    assert response.status_code == 202, response.text
    run = response.json()
    assert bob.post("/api/runs/" + run["id"] + "/approval", json={"resolution": "granted"}).status_code == 404
    grant(alice, run)
    with control_session_factory()() as queue:
        assert tick(queue, "private-purge-mutation") == run["id"]
    result = alice.get("/api/runs/" + run["id"]).json()
    assert result["status"] == "succeeded", result
    assert alice.get("/api/artifacts/" + own["id"]).json()["purged_at"]
    assert bob.get("/api/artifacts/" + other["id"] + "/file").status_code == 200


def test_competing_private_library_edits_accept_only_one_expected_version(accounts):
    _, alice, _ = accounts
    artifact = upload(alice)
    path = "/api/artifacts/" + artifact["id"]

    def edit(title):
        response = alice.patch(path, json={"title": title, "expected_updated_at": None})
        return title, response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(edit, ["Synthetic first device", "Synthetic second device"]))
    assert sorted(status for _, status in responses) == [200, 409], responses
    assert alice.get(path).json()["title"] == next(title for title, status in responses if status == 200)


def test_private_lock_refreshes_cached_snapshot_and_never_locks_foreign_or_inspected_data(accounts):
    _, alice, bob = accounts
    own, other = upload(alice), upload(bob)
    with control_session_factory()() as control:
        owner_id = control.get(Artifact, own["id"]).owner_id
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id), expire_on_commit=False) as session:
        cached = session.get(Artifact, own["id"])
        session.commit()
        with control_session_factory()() as second_device:
            changed = second_device.get(Artifact, own["id"])
            changed.title, changed.library_updated_at = "Synthetic newer snapshot", utcnow()
            second_device.commit()
        assert cached.title != "Synthetic newer snapshot"
        locked = private_for_update(session, Artifact, own["id"])
        assert locked is cached and locked.title == "Synthetic newer snapshot"
        assert locked.library_updated_at is not None
        assert private_for_update(session, Artifact, other["id"]) is None
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id, inspect_all=True)) as inspection:
        with pytest.raises(DataAccessError, match="read-only"):
            private_for_update(inspection, Artifact, own["id"])
