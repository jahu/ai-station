"""Shared model activity guards do not grant access to foreign private Runs."""

from app.data_access import data_session_for_run
from app.db import control_session_factory
from app.engine import tick
from app.llama import evict_idle_models
from app.models import Run, RuntimeInstance
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_llama import managed as managed


def runtime(owner, model):
    response = owner.post("/api/llama/load", json={"model_file_id": model, "gpus": [2, 7]})
    assert response.status_code == 202, response.text
    with control_session_factory()() as queue:
        tick(queue, "shared-model-fixture")
        run = queue.get(Run, response.json()["id"])
        assert run.status == "succeeded", run.error_message
        instance = queue.get(RuntimeInstance, run.parameters["instance_id"])
        return instance.id, instance.endpoint


def active(browser, instance_id, endpoint, *, operation=False):
    response = browser.post("/api/testing/runs", json={"title": "Synthetic private consumer marker"})
    assert response.status_code == 202
    with control_session_factory()() as queue:
        row = queue.get(Run, response.json()["id"])
        row.parameters = {"instance_id": instance_id} if operation else {"endpoint": endpoint}
        if operation:
            row.executor_type = "llama_health"
        queue.commit()
        return row.id


def test_another_accounts_consumer_blocks_stop_restart_and_automatic_eviction(accounts, managed):
    owner, alice, _ = accounts
    instance_id, endpoint = runtime(owner, managed[0])
    foreign_id = active(alice, instance_id, endpoint)
    for action in ("stop", "restart"):
        response = owner.post(f"/api/llama/{instance_id}/{action}", json={})
        assert response.status_code == 409, response.text
        assert foreign_id not in response.text and "Synthetic private" not in response.text
    assert owner.get("/api/runs/" + foreign_id).status_code == 404
    own = owner.post("/api/testing/runs", json={"title": "Synthetic GPU requester"}).json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, own).owner_id
    with data_session_for_run(own, owner_id) as session:
        evict_idle_models(session, session.get(Run, own), [2, 7], desired={2})
        session.commit()
    with control_session_factory()() as queue:
        assert not list(queue.scalars(select(Run).where(Run.executor_type == "llama_stop")))
        assert queue.get(RuntimeInstance, instance_id).status == "ready"
    assert managed[1][instance_id]["status"] == "ready"


def test_another_accounts_operation_is_only_a_busy_fact_and_never_a_foreign_run_lookup(accounts, managed):
    owner, alice, _ = accounts
    instance_id, endpoint = runtime(owner, managed[0])
    foreign_id = active(alice, instance_id, endpoint, operation=True)
    response = owner.post(f"/api/llama/{instance_id}/health", json={})
    assert response.status_code == 409 and foreign_id not in response.text
    assert owner.get("/api/runs/" + foreign_id).status_code == 404
    assert alice.get("/api/runs/" + foreign_id).status_code == 200
    with control_session_factory()() as queue:
        queue.get(Run, foreign_id).status = "succeeded"
        queue.commit()
    response = owner.post(f"/api/llama/{instance_id}/health", json={})
    assert response.status_code == 202, response.text
