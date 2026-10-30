"""Real A/B/admin HTTP inspection; no production data or native workloads."""

from uuid import uuid4

import pytest
from app import models as m
from app.account_inspection import COLLECTIONS
from app.data_access import DataAccessError, DataScope, ScopedSession
from app.db import control_session_factory, get_engine, utcnow
from app.events import append_event
from sqlalchemy import func, select
from sqlalchemy.orm import make_transient_to_detached
from test_account_private_api import accounts, private_app, upload  # noqa: F401


@pytest.fixture
def workspaces(accounts):  # noqa: F811 - imported pytest fixture
    admin, alice, bob = accounts
    owners = {}
    for name, browser in (("Alice", alice), ("Bob", bob)):
        user_id = browser.get("/api/auth").json()["user"]["id"]
        with control_session_factory()() as session:
            conversation = m.Conversation(owner_id=user_id, title=f"{name} conversation")
            task = m.Task(owner_id=user_id, title=f"{name} task", prompt=f"{name} private prompt")
            session.add_all([conversation, task])
            session.flush()
            run = m.Run(owner_id=user_id, task_id=task.id, capability=f"{name} execution")
            session.add(run)
            session.flush()
            for index in range(3):
                session.add(
                    m.Message(conversation_id=conversation.id, role="user", content=f"{name} message {index}")
                )
                append_event(session, run.id, "private.event", {"text": f"{name} event {index}"})
            rows = {
                "conversations": conversation,
                "tasks": task,
                "runs": run,
                "memory": m.MemoryEntry(
                    owner_id=user_id, scope="global", content=f"{name} private fact", enabled=False
                ),
                "agents": m.Agent(owner_id=user_id, name=f"{name} agent"),
                "projects": m.Project(
                    owner_id=user_id, name=f"{name} project", repo_path=f"/synthetic/{name}"
                ),
                "approvals": m.Approval(owner_id=user_id, run_id=run.id, action=f"{name} approval"),
                "providers": m.ChatProvider(
                    owner_id=user_id,
                    key="private",
                    name=f"{name} provider",
                    secret_ref="file:secrets/DO-NOT-RESOLVE",
                ),
                "connectors": m.Connector(
                    owner_id=user_id,
                    key="private",
                    name=f"{name} connector",
                    secret_ref="env:DO_NOT_RESOLVE",
                    config_json={
                        "url": "https://example.org",
                        "secret": "MUST-NOT-APPEAR",
                        "smtp": {"host": "smtp.example.org", "password": "MUST-NOT-APPEAR"},
                    },
                ),
            }
            session.add_all(rows.values())
            session.add_all(
                [
                    m.UserSetting(user_id=user_id, key="conversation_preferences", value={"model": name}),
                    m.UserSetting(user_id=user_id, key="auth.totp", value={"seed": "MUST-NOT-APPEAR"}),
                    m.UserSetting(
                        user_id=user_id, key="unknown.private", value={"secret": "MUST-NOT-APPEAR"}
                    ),
                ]
            )
            session.commit()
            owners[name] = {"id": user_id, **{key: row.id for key, row in rows.items()}}
        artifact_id, content = upload(browser, "red" if name == "Alice" else "blue")
        owners[name].update(artifacts=artifact_id, bytes=content)
    return admin, alice, bob, owners


def base(owner):
    return f"/api/admin/users/{owner['id']}/workspace"


def test_all_private_collections_and_counts_are_fixed_to_selected_owner(workspaces):
    admin, _, _, owners = workspaces
    alice, bob = owners["Alice"], owners["Bob"]
    response = admin.get(base(alice))
    assert response.status_code == 200, response.text
    overview = response.json()
    assert overview["read_only"] and overview["user"]["id"] == alice["id"]
    assert overview["preferences"] == {"conversation_preferences": {"model": "Alice"}}
    assert "MUST-NOT-APPEAR" not in response.text
    for category, (model, _, _) in COLLECTIONS.items():
        with control_session_factory()() as session:
            count = session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == alice["id"])
            )
        assert overview["counts"][category] == count
        response = admin.get(f"{base(alice)}/{category}?limit=1")
        assert response.status_code == 200, (category, response.text)
        assert response.json()["total"] == count
        all_rows = admin.get(f"{base(alice)}/{category}?limit=100").json()["items"]
        assert alice[category] in [row["id"] for row in all_rows]
        assert bob[category] not in [row["id"] for row in all_rows]
        assert admin.get(f"{base(alice)}/{category}/{alice[category]}").status_code == 200
        assert admin.get(f"{base(alice)}/{category}/{bob[category]}").status_code == 404
        assert admin.get(f"{base(alice)}/{category}?search=Bob").json()["total"] == 0
    # A private inspection never changes the administrator's ordinary workspace.
    assert admin.get("/api/runs").json() == []
    assert admin.get("/api/auth").json()["user"]["username"] == "Owner"


def test_members_cannot_inspect_even_their_own_workspace(workspaces):
    _, alice, bob, owners = workspaces
    for browser in (alice, bob):
        for path in (base(owners["Alice"]), base(owners["Bob"]), f"/api/admin/users/{uuid4()}/workspace"):
            assert browser.get(path).status_code == 403
        assert (
            browser.get(f"{base(owners['Alice'])}/artifacts/{owners['Alice']['artifacts']}/file").status_code
            == 403
        )


def test_messages_events_paging_and_validation(workspaces):
    admin, _, _, owners = workspaces
    alice, bob = owners["Alice"], owners["Bob"]
    for category in ("runs", "conversations"):
        path = f"{base(alice)}/{category}/{alice[category]}/entries"
        first = admin.get(path + "?limit=2").json()
        last = admin.get(path + "?limit=2&offset=2").json()
        assert first["total"] == last["total"] == 3
        assert len(first["items"]) == 2 and len(last["items"]) == 1
        assert set(row["id"] for row in first["items"]).isdisjoint(row["id"] for row in last["items"])
        assert admin.get(f"{base(alice)}/{category}/{bob[category]}/entries").status_code == 404
    assert admin.get(f"{base(alice)}/runs?limit=101").status_code == 422
    assert admin.get(f"{base(alice)}/runs?offset=-1").status_code == 422
    assert admin.get(f"{base(alice)}/users").status_code == 422
    assert admin.get(f"{base(alice)}/memory?search=%25").json()["total"] == 0


def test_credential_values_and_paths_are_never_resolved_or_returned(workspaces, monkeypatch):
    import app.secrets

    admin, _, _, owners = workspaces

    def forbidden(*_args, **_kwargs):
        pytest.fail("Inspection must not resolve credentials")

    monkeypatch.setattr(app.secrets, "resolve_secret", forbidden)
    for category in ("providers", "connectors"):
        response = admin.get(f"{base(owners['Alice'])}/{category}/{owners['Alice'][category]}")
        assert response.status_code == 200
        assert response.json()["credential_configured"]
        assert not any(
            value in response.text for value in ("MUST-NOT-APPEAR", "DO-NOT-RESOLVE", "DO_NOT_RESOLVE")
        )


def test_media_ranges_subject_binding_deletion_and_path_boundary(workspaces, tmp_path):
    from app.config import get_settings

    admin, _, _, owners = workspaces
    alice, bob = owners["Alice"], owners["Bob"]
    path = f"{base(alice)}/artifacts/{alice['artifacts']}/file"
    response = admin.get(path, headers={"Range": "bytes=0-7"})
    assert response.status_code == 206 and response.content == alice["bytes"][:8]
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert admin.get(f"{base(alice)}/artifacts/{bob['artifacts']}/file").status_code == 404
    with control_session_factory()() as session:
        artifact = session.get(m.Artifact, alice["artifacts"])
        artifact.purged_at = utcnow()
        session.commit()
    assert admin.get(path).status_code == 410
    assert admin.get(f"{base(alice)}/artifacts/{alice['artifacts']}").status_code == 200
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private outside data")
    link = get_settings().data_dir / "artifacts" / "inspection-escape.png"
    link.symlink_to(outside)
    with control_session_factory()() as session:
        artifact = session.get(m.Artifact, alice["artifacts"])
        artifact.purged_at = None
        artifact.relative_path = "artifacts/inspection-escape.png"
        session.commit()
    assert admin.get(path).status_code == 404


def test_no_inspection_write_endpoints_and_disabled_subject_remains_readable(workspaces):
    admin, _, _, owners = workspaces
    alice = owners["Alice"]
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        response = admin.request(
            method, f"{base(alice)}/tasks/{alice['tasks']}", json={"title": "not allowed"}
        )
        assert response.status_code == 405
    with control_session_factory()() as session:
        subject = session.get(m.User, alice["id"])
        subject.enabled = False
        session.commit()
    assert admin.get(base(alice)).status_code == 200
    assert admin.get(f"{base(alice)}/tasks/{alice['tasks']}").json()["title"] == "Alice task"


@pytest.mark.parametrize("change", ["demote", "disable", "revoke"])
def test_actor_authority_rechecked_for_details_and_media(workspaces, change):
    admin, _, _, owners = workspaces
    alice = owners["Alice"]
    actor_id = admin.get("/api/auth").json()["user"]["id"]
    assert admin.get(base(alice)).status_code == 200
    with control_session_factory()() as session:
        actor = session.get(m.User, actor_id)
        if change == "demote":
            actor.is_admin = False
        elif change == "disable":
            actor.enabled = False
        else:
            for device in session.scalars(select(m.UserSession).where(m.UserSession.user_id == actor_id)):
                device.revoked_at = utcnow()
        session.commit()
    for path in (
        base(alice),
        f"{base(alice)}/tasks/{alice['tasks']}",
        f"{base(alice)}/artifacts/{alice['artifacts']}/file",
    ):
        assert admin.get(path).status_code == (403 if change == "demote" else 401)


def test_selected_scope_identity_map_counts_and_writes(workspaces):
    admin, _, _, owners = workspaces
    actor = admin.get("/api/auth").json()["user"]["id"]
    alice, bob = owners["Alice"], owners["Bob"]
    scope = DataScope(actor, inspect_all=True, administrator=True, inspection_owner_id=alice["id"])
    with ScopedSession(bind=get_engine(), scope=scope) as session:
        # Deliberately attach a foreign detached identity. Session.get must not
        # bypass selection when no SELECT occurs.
        foreign = m.Task(id=bob["tasks"], owner_id=bob["id"], title="Foreign cached task")
        make_transient_to_detached(foreign)
        session.add(foreign)
        assert session.get(m.Task, bob["tasks"]) is None
        assert session.scalar(select(func.count()).select_from(m.Task)) == 1
        assert [row.content for row in session.scalars(select(m.Message))] == [
            f"Alice message {index}" for index in range(3)
        ]
        own = session.get(m.Task, alice["tasks"])
        own.title = "Cannot mutate while inspecting"
        with pytest.raises(DataAccessError, match="read-only"):
            session.flush()
    with pytest.raises(DataAccessError):
        DataScope(actor, inspection_owner_id=alice["id"])
