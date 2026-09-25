from app.api import app
from app.db import reset_engine, session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import RuntimeInstance
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import request_cancel
from fastapi.testclient import TestClient


def launch(api):
    queued = api.post("/api/runtimes/observe", json={})
    assert queued.status_code == 202, queued.text
    return queued.json()


def execute():
    with session_factory()() as session:
        tick(session, "runtime-test")


def inventory(*, complete=True, items=True):
    return {
        "complete": complete,
        "inspected": 1,
        "instances": [{"identity": "a" * 64, "runtime_key": "ollama", "pid": 42, "start_ticks": 500}]
        if items
        else [],
    }


def test_observation_persistence_identity_and_missing_semantics(monkeypatch):
    response = inventory()
    monkeypatch.setattr(RunnerClient, "observe_runtimes", lambda self: response)
    monkeypatch.setattr(LocalChatProvider, "models", lambda self: ["fake-model"])
    api = TestClient(app)
    queued = launch(api)
    assert api.post("/api/runtimes/observe", json={}).status_code == 409
    execute()
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "succeeded"
    rows = api.get("/api/runtimes").json()["items"]
    assert len(rows) == 2 and all(row["ownership"] == "external" for row in rows)
    process = next(row for row in rows if row["runtime_key"] == "ollama")
    assert process["status"] == "observed" and process["metadata"]["pid"] == 42
    assert api.get("/api/artifacts", params={"run_id": queued["id"]}).json()[0]["type"] == "json"
    reset_engine()
    launch(api)
    execute()
    assert {row["id"] for row in api.get("/api/runtimes").json()["items"]} == {row["id"] for row in rows}
    response = inventory(items=False, complete=False)
    launch(api)
    execute()
    with session_factory()() as session:
        assert session.get(RuntimeInstance, process["id"]).status == "unknown"
    response = inventory(items=False)
    launch(api)
    execute()
    with session_factory()() as session:
        assert session.get(RuntimeInstance, process["id"]).status == "not_observed"


def test_failure_preserves_previous_registry_and_cancellation_never_updates(monkeypatch):
    monkeypatch.setattr(RunnerClient, "observe_runtimes", lambda self: inventory())
    monkeypatch.setattr(LocalChatProvider, "models", lambda self: [])
    api = TestClient(app)
    launch(api)
    execute()
    before = api.get("/api/runtimes").json()["items"]

    def unavailable(self):
        raise RunnerUnavailable("unavailable")

    monkeypatch.setattr(RunnerClient, "observe_runtimes", unavailable)
    failed = launch(api)
    execute()
    assert api.get("/api/runs/" + failed["id"]).json()["status"] == "failed"
    assert api.get("/api/runtimes").json()["items"] == before
    queued = launch(api)

    def cancel(self):
        from app.models import Run

        with session_factory()() as session:
            request_cancel(session, session.get(Run, queued["id"]))
            session.commit()
        return inventory(items=False)

    monkeypatch.setattr(RunnerClient, "observe_runtimes", cancel)
    execute()
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "canceled"
    assert api.get("/api/runtimes").json()["items"] == before


def test_no_runtime_mutation_or_arbitrary_probe_url():
    api = TestClient(app)
    assert api.post("/api/runtimes/observe", json={"endpoint": "http://example.com"}).status_code == 422
    assert api.post("/api/runtimes/stop", json={"pid": 1}).status_code == 404
