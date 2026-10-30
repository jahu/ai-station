"""Real owner-scoped API/worker integration with a tiny controlled CPU child."""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.data_access import DataAccessError, data_session_for_run
from app.db import control_session_factory
from app.embeddings import _activate_prepared_model, load_setup, save_setup
from app.engine import tick
from app.models import Run, Setting, User
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_managed_embeddings import cpu as cpu
from test_managed_embeddings import installed as installed


def drain():
    for _ in range(12):
        with control_session_factory()() as queue:
            if tick(queue, "private-embedding-fixture") is None:
                return
    raise AssertionError("The owned embedding queue did not finish")


def prepare(browser):
    setup = browser.get("/api/memory/embeddings/setup").json()
    return browser.post("/api/memory/embeddings/prepare", json={"expected_revision": setup["revision"]})


def test_one_shared_model_has_private_activity_indexes_search_and_cancellable_runs(accounts, cpu):
    owner, alice, bob = accounts
    for browser, text in ((alice, "Apples private Alice memory"), (bob, "Pear private Bob memory")):
        assert browser.post("/api/memory", json={"scope": "global", "content": text}).status_code == 201
    response = prepare(owner)
    assert response.status_code == 202, response.text
    prepare_id = response.json()["id"]
    drain()
    result = owner.get("/api/runs/" + prepare_id).json()
    assert result["status"] == "succeeded", result
    assert owner.get("/api/memory/embeddings/setup").json()["prepare_run"]["id"] == prepare_id
    for browser in (alice, bob):
        setup = browser.get("/api/memory/embeddings/setup").json()
        assert setup["configured"] and setup["backend"] == "local_cpu"
        assert setup["prepare_run"] is setup["health_run"] is setup["index_run"] is None
        assert prepare_id not in str(setup)
    ids = []
    for browser in (alice, bob):
        response = browser.post("/api/memory/embeddings/index")
        assert response.status_code == 202, response.text
        assert response.json()["parameters"]["secret_ref"] == ""
        ids.append(response.json()["id"])
    drain()
    for browser, own_id, other_id in ((alice, ids[0], ids[1]), (bob, ids[1], ids[0])):
        setup = browser.get("/api/memory/embeddings/setup").json()
        assert setup["indexed_count"] == setup["memory_count"] == 1
        assert setup["index_run"]["id"] == own_id and setup["index_run"]["status"] == "succeeded", setup
        assert other_id not in str(setup)
        assert browser.get("/api/runs/" + other_id).status_code == 404
        response = browser.post("/api/memory/embeddings/search", json={"query": "Pear"})
        assert response.status_code == 202, response.text
        drain()
        result = browser.get("/api/runs/" + response.json()["id"]).json()
        assert result["status"] == "succeeded", result
        assert len(result["metadata"]["results"]) == 1
        assert ("Alice" if browser is alice else "Bob") in result["metadata"]["results"][0]["content"]
    with control_session_factory()() as queue:
        shared = queue.get(Setting, "memory_embeddings").value
        assert not any(
            shared.get(key) for key in ("prepare_run_id", "last_health_run_id", "last_index_run_id")
        )
    assert len(cpu) >= 5


def test_shared_preparation_busy_check_does_not_expose_another_administrators_run(accounts, cpu):
    owner, _, _ = accounts
    assert (
        owner.post(
            "/api/admin/users",
            json={"username": "OtherAdmin", "password": "synthetic other admin password", "is_admin": True},
        ).status_code
        == 201
    )
    from app.api import app
    from test_account_private_api import browser

    second = browser(app)
    assert (
        second.post(
            "/api/auth/login", json={"username": "OtherAdmin", "password": "synthetic other admin password"}
        ).status_code
        == 200
    )
    queued = prepare(owner)
    assert queued.status_code == 202
    blocked = prepare(second)
    assert blocked.status_code == 409 and queued.json()["id"] not in blocked.text
    assert not cpu


def test_administrator_demotion_prevents_queued_model_activation(accounts, cpu):
    owner, _, _ = accounts
    queued = prepare(owner)
    assert queued.status_code == 202
    with control_session_factory()() as queue:
        row = queue.get(Run, queued.json()["id"])
        queue.get(User, row.owner_id).is_admin = False
        queue.commit()
    drain()
    with control_session_factory()() as queue:
        row = queue.get(Run, queued.json()["id"])
        assert row.status == "failed" and row.error_type == "AccountPermissionDenied"
        assert queue.get(Setting, "memory_embeddings") is None
    assert not cpu


def test_execution_cannot_change_shared_configuration_or_attach_foreign_activity(accounts, cpu):
    owner, alice, bob = accounts
    assert prepare(owner).status_code == 202
    drain()
    own = alice.post("/api/memory/embeddings/health").json()["id"]
    other = bob.post("/api/memory/embeddings/health").json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, own).owner_id
        original = dict(queue.get(Setting, "memory_embeddings").value)
    with data_session_for_run(own, owner_id) as session:
        current = load_setup(session)
        with pytest.raises(DataAccessError, match="administrator request"):
            save_setup(session, {**current, "revision": current["revision"] + 1, "model": "unreviewed-model"})
        with pytest.raises(DataAccessError, match="executing account"):
            save_setup(session, {**current, "last_health_run_id": other})
        session.rollback()
    with control_session_factory()() as queue:
        assert queue.get(Setting, "memory_embeddings").value == original


def test_activation_rechecks_cached_administrator_authority_before_machine_write(accounts, cpu):
    from app.embedding_models import DIMENSION, MODEL_ID
    from app.runs import transition
    from app.state import RunStatus

    owner, _, _ = accounts
    queued = prepare(owner).json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, queued).owner_id
    with data_session_for_run(queued, owner_id) as session:
        cached = session.get(User, owner_id)
        assert cached.is_admin
        run = session.get(Run, queued)
        for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
            transition(session, run, state, event_type="run." + state.value)
        # Simulate authoritative role change while the identity map still has
        # the old role; no actual account or process outside this DB is touched.
        session.connection().execute(
            User.__table__.update().where(User.id == owner_id).values(is_admin=False)
        )
        with pytest.raises(DataAccessError, match="authorized owned preparation"):
            _activate_prepared_model(
                session,
                run,
                {
                    "backend": "local_cpu",
                    "model": MODEL_ID,
                    "model_id": MODEL_ID,
                    "revision": 1,
                    "dimension": DIMENSION,
                },
            )
        assert not cached.is_admin
        session.rollback()
    assert not cpu


def test_endpoint_health_uses_private_activity_and_never_exposes_machine_credential_reference(
    accounts, monkeypatch
):
    owner, alice, _ = accounts
    monkeypatch.setenv("SYNTHETIC_EMBED_KEY", "synthetic-test-value")
    response = owner.put(
        "/api/memory/embeddings/setup",
        json={
            "endpoint": "http://127.0.0.1:9999/v1",
            "model": "synthetic-embedding",
            "secret_ref": "env:SYNTHETIC_EMBED_KEY",
        },
    )
    assert response.status_code == 200, response.text
    calls = []

    async def embed(endpoint, model, text, secret_ref):
        assert endpoint == "http://127.0.0.1:9999/v1" and model == "synthetic-embedding"
        assert secret_ref == "env:SYNTHETIC_EMBED_KEY"
        calls.append(text)
        return [1.0] * 8

    monkeypatch.setattr("app.embeddings.embed_text", embed)
    response = alice.post("/api/memory/embeddings/health")
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert "SYNTHETIC_EMBED_KEY" not in response.text
    drain()
    result = alice.get("/api/runs/" + run_id).json()
    assert result["status"] == "succeeded", result
    own = alice.get("/api/memory/embeddings/setup").json()
    assert own["dimension"] == 8 and own["health_run"]["id"] == run_id
    assert owner.get("/api/memory/embeddings/setup").json()["health_run"] is None
    assert calls == ["ai-station embedding probe"]


def test_only_owner_can_cancel_cpu_memory_work_and_other_accounts_remain_usable(accounts, cpu):
    owner, alice, bob = accounts
    assert prepare(owner).status_code == 202
    drain()
    memory = alice.post(
        "/api/memory", json={"scope": "global", "content": "Retain Alice private memory"}
    ).json()["id"]
    response = alice.post("/api/memory/embeddings/search", json={"query": "HOLD"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    count = len(cpu)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(drain)
        try:
            deadline = time.monotonic() + 10
            while len(cpu) == count:
                assert time.monotonic() < deadline, "Owned CPU child was not started"
                time.sleep(0.02)
            assert bob.post("/api/runs/" + run_id + "/cancel").status_code == 404
            assert alice.post("/api/runs/" + run_id + "/cancel").status_code == 200
            future.result(timeout=10)
        finally:
            if not future.done():
                alice.post("/api/runs/" + run_id + "/cancel")
    result = alice.get("/api/runs/" + run_id).json()
    assert result["status"] == "canceled" and result["metadata"]["cpu_process_confirmed_gone"], result
    assert not Path(f"/proc/{cpu[-1]}").exists()
    assert alice.get("/api/memory/" + memory).status_code == 200
    queued = bob.post("/api/testing/runs", json={"title": "Bob independent work"})
    assert queued.status_code == 202
    drain()
    assert bob.get("/api/runs/" + queued.json()["id"]).json()["status"] == "succeeded"
