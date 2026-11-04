"""A/B/admin tests against the real monolith, not a filtered mock repository."""

import io

import pytest
from app.account_http import install_account_access
from app.api import app
from app.db import control_session_factory
from app.events import append_event
from app.models import Run
from fastapi.testclient import TestClient
from PIL import Image

PASSWORD = "synthetic private account password"


@pytest.fixture
def private_app(monkeypatch):
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_ACCESS_PROFILE", "accounts")
    clear_settings_cache()
    routes = list(app.router.routes)
    handlers = dict(app.exception_handlers)
    previous = getattr(app.state, "account_access_enabled", False)
    app.middleware_stack = None
    install_account_access(app)
    try:
        yield app
    finally:
        app.router.routes = routes
        app.exception_handlers = handlers
        app.state.account_access_enabled = previous
        app.middleware_stack = None
        app.openapi_schema = None


def browser(application):
    return TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))


@pytest.fixture
def accounts(private_app):
    owner = browser(private_app)
    created = owner.post("/api/auth/setup", json={"username": "Owner", "password": PASSWORD})
    assert created.status_code == 201, created.text
    users = {}
    for username in ("Alice", "Bob"):
        response = owner.post("/api/admin/users", json={"username": username, "password": PASSWORD})
        assert response.status_code == 201, response.text
        member = browser(private_app)
        response = member.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert response.status_code == 200, response.text
        users[username] = member
    return owner, users["Alice"], users["Bob"]


def run(browser, title):
    response = browser.post("/api/testing/runs", json={"title": title})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def upload(browser, color):
    output = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(output, "PNG")
    response = browser.post(
        "/api/images/uploads", files={"file": (color + ".png", output.getvalue(), "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], output.getvalue()


def test_public_health_and_anonymous_private_denial(private_app):
    anonymous = browser(private_app)
    assert anonymous.get("/api/health").status_code == 200
    assert anonymous.get("/api/auth").json()["setup_required"]
    for path in ("/api/runs", "/api/artifacts", "/api/memory", "/api/chat/conversations", "/api/dashboard"):
        response = anonymous.get(path)
        assert response.status_code == 401 and response.headers["cache-control"] == "no-store", path


def test_member_workspace_catalogs_and_private_settings_are_usable(accounts):
    _, alice, _ = accounts
    failures = {}
    for path in (
        "/api/chat/providers",
        "/api/chat/model-catalog",
        "/api/chat/preferences",
        "/api/generation/preferences",
        "/api/images/models",
        "/api/agents/tools",
        "/api/skills",
        "/api/audio/music/capabilities",
        "/api/video/capabilities",
        "/api/avatars/capabilities",
        "/api/llama",
        "/api/memory/embeddings/setup",
        "/api/dashboard",
    ):
        response = alice.get(path)
        if response.status_code != 200:
            failures[path] = {"status": response.status_code, "detail": response.text[:250]}
    assert failures == {}


def test_shared_embedding_model_readiness_hides_foreign_activity_and_credential_references(accounts):
    from app.models import Setting

    owner, alice, _ = accounts
    private_run = run(owner, "Private administrator embedding check")
    assert (
        alice.post("/api/memory", json={"content": "Alice private fact", "scope": "global"}).status_code
        == 201
    )
    with control_session_factory()() as session:
        session.add(
            Setting(
                key="memory_embeddings",
                value={
                    "endpoint": "http://127.0.0.1:1/v1",
                    "model": "shared-embedding-model",
                    "dimension": 3,
                    "secret_ref": "env:SYNTHETIC_EMBED_SECRET",
                    "last_health_run_id": private_run,
                    "last_index_run_id": private_run,
                },
            )
        )
        session.commit()
    response = alice.get("/api/memory/embeddings/setup")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] and body["model"] == "shared-embedding-model" and body["memory_count"] == 1
    assert body["last_health_run_id"] is body["last_index_run_id"] is None
    assert body["health_run"] is body["index_run"] is None
    assert private_run not in response.text and "SYNTHETIC_EMBED_SECRET" not in response.text
    assert alice.put("/api/memory/embeddings/setup", json={"clear": True}).status_code == 403
    assert alice.post("/api/memory/embeddings/prepare", json={"expected_revision": 0}).status_code == 403


def test_run_list_detail_events_and_sse_are_owner_scoped(accounts):
    _, alice, bob = accounts
    ids = [run(alice, "Private Alice task"), run(bob, "Private Bob task")]
    with control_session_factory()() as session:
        for index, identity in enumerate(ids):
            row = session.get(Run, identity)
            row.status = "succeeded"
            row.parameters = {"synthetic_private_text": "Alice-only" if index == 0 else "Bob-only"}
            append_event(
                session, identity, "test.private", {"text": row.parameters["synthetic_private_text"]}
            )
        session.commit()
    assert [row["id"] for row in alice.get("/api/runs").json()] == ids[:1]
    for suffix in ("", "/events", "/stream"):
        response = alice.get("/api/runs/" + ids[1] + suffix)
        assert response.status_code == 404 and "Bob-only" not in response.text
    own = alice.get("/api/runs/" + ids[0] + "/stream")
    assert own.status_code == 200 and "Alice-only" in own.text and "Bob-only" not in own.text
    assert own.headers["cache-control"] == "no-store"
    for action in ("cancel", "approval", "retry-workflow"):
        response = alice.post(
            "/api/runs/" + ids[1] + "/" + action,
            json={"resolution": "granted"} if action == "approval" else None,
        )
        assert response.status_code == 404, response.text


def test_library_files_thumbnails_lineage_and_mutations_cannot_access_another_owner(accounts):
    _, alice, bob = accounts
    own, own_bytes = upload(alice, "blue")
    other, _ = upload(bob, "green")
    response = alice.get("/api/artifacts")
    assert response.status_code == 200
    assert own in response.text and other not in response.text
    for suffix in ("", "/file", "/thumbnail", "/lineage"):
        assert alice.get("/api/artifacts/" + other + suffix).status_code == 404
    assert alice.get("/api/artifacts/" + own + "/file").content == own_bytes
    assert (
        alice.get("/api/artifacts/" + own + "/file", headers={"Range": "bytes=0-15"}).content
        == own_bytes[:16]
    )
    version = {"expected_updated_at": "2026-10-30T00:00:00+00:00"}
    assert alice.request("DELETE", "/api/artifacts/" + other, json=version).status_code == 404
    assert alice.patch("/api/artifacts/" + other, json={**version, "title": "Illegal"}).status_code == 404
    assert bob.get("/api/artifacts/" + other + "/file").status_code == 200


def test_global_memory_is_personal_and_fts_and_edits_do_not_cross_accounts(accounts):
    _, alice, bob = accounts
    ids = []
    for name, member in (("Alice", alice), ("Bob", bob)):
        response = member.post(
            "/api/memory", json={"scope": "global", "content": name + " sharedphrase private memory"}
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    response = alice.get("/api/memory", params={"q": "sharedphrase"})
    assert response.status_code == 200 and ids[0] in response.text and ids[1] not in response.text
    assert alice.get("/api/memory/" + ids[1]).status_code == 404
    assert (
        alice.request(
            "DELETE", "/api/memory/" + ids[1], json={"expected_updated_at": "2026-10-30T00:00:00+00:00"}
        ).status_code
        == 404
    )
    assert bob.get("/api/memory/" + ids[1]).status_code == 200


def test_preferences_are_personal_and_versions_do_not_collide_between_accounts(accounts):
    _, alice, bob = accounts
    original = bob.get("/api/chat/preferences")
    assert original.status_code == 200, original.text
    changed = alice.put(
        "/api/chat/preferences",
        json={**original.json(), "send_key": "ctrl-enter", "web_search_enabled": False},
    )
    assert changed.status_code == 200, changed.text
    assert bob.get("/api/chat/preferences").json() == original.json()
    assert alice.get("/api/chat/preferences").json()["send_key"] == "ctrl-enter"
    initial = bob.get("/api/generation/preferences")
    assert initial.status_code == 200, initial.text
    changed = alice.put(
        "/api/generation/preferences", json={**initial.json(), "model": "synthetic-local-translator"}
    )
    assert changed.status_code == 200, changed.text
    assert bob.get("/api/generation/preferences").json() == initial.json()


def test_admin_inspection_is_explicit_read_only_and_never_implicit_context(accounts):
    owner, alice, bob = accounts
    ids = [run(alice, "Alice private"), run(bob, "Bob private")]
    assert owner.get("/api/runs").json() == []
    headers = {"X-AI-Station-Inspect-All": "true"}
    inspected = owner.get("/api/runs", headers=headers)
    assert inspected.status_code == 200 and {row["id"] for row in inspected.json()} == set(ids)
    assert alice.get("/api/runs", headers=headers).status_code == 403
    assert (
        owner.post(
            "/api/testing/runs", json={"title": "Illegal inspector mutation"}, headers=headers
        ).status_code
        == 403
    )
    assert owner.get("/api/runs").json() == []


def test_member_machine_operations_and_old_password_only_auth_are_closed(accounts):
    owner, alice, _ = accounts
    for path in (
        "/api/maintenance",
        "/api/nodes",
        "/api/private-access",
        "/api/runtimes",
        "/api/system/status",
        "/api/system/diagnostics",
        "/api/system/gpu-processes",
    ):
        assert alice.get(path).status_code == 403, path
    for path in ("/api/coding/cursor", "/api/coding/codex", "/api/projects", "/api/models/discover"):
        assert alice.post(path, json={}).status_code == 403, path
    assert owner.post("/api/operator-auth/login", json={"password": PASSWORD}).status_code == 410
    assert owner.put("/api/operator-auth", json={"password": "synthetic replacement"}).status_code == 410
