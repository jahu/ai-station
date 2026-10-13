import copy
from datetime import timedelta

import pytest
from app import browser
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.runner_client import RunnerClient
from app.runs import request_cancel
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


def fake_runner(monkeypatch, *, exit_code=0, canceled=False, uncertain=False):
    reports = {}
    canceled_ids = []

    def request(self, method, path, payload=None):
        if path == "/v1/browser/capabilities":
            return {"available": True}
        if path == "/v1/runs/browser":
            run_id = payload["run_id"]
            pages = []
            for index, url in enumerate(payload["urls"]):
                relative = f"runtime/browser/{run_id}/page-{index}.png"
                target = get_settings().data_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1240, 800)).save(target)
                pages.append(
                    {
                        "url": url,
                        "title": "Rendered company",
                        "text": "Visible JavaScript text",
                        "screenshot_path": relative,
                        "requests": [{"url": url, "method": "GET", "status": 200}],
                        "links": [],
                        "status": 200,
                        "truncated": False,
                    }
                )
            reports[run_id] = {
                "run_id": run_id,
                "urls": payload["urls"],
                "pages": pages,
                "captured_at": utcnow().timestamp(),
            }
            if canceled:
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, run_id))
                    session.commit()
            return {
                "pid": 12,
                "process_group_id": 12,
                "runner_id": "fake",
                "stdout_log": "runs/x/out",
                "stderr_log": "runs/x/err",
            }
        if path.startswith("/v1/process/") and method == "GET":
            return {
                "alive": False,
                "completion_pending": False,
                "status": "interrupted" if uncertain else "canceled" if canceled else "exited",
                "exit_code": None if uncertain else exit_code,
                "cleanup_confirmed": not uncertain,
                "stdout": "",
                "stderr": "",
                "stderr_tail": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }
        if path == "/v1/process/cancel":
            canceled_ids.append(payload["run_id"])
            return {}
        if path.endswith("/report"):
            return reports[path.split("/")[-2]]
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(RunnerClient, "request", request)
    monkeypatch.setattr(browser, "available", lambda: {"available": True})
    return reports, canceled_ids


def run_worker():
    with session_factory()() as session:
        tick(session, "browser-test")


def test_unavailable_browser_and_private_inputs_fail_without_queueing():
    api = TestClient(app)
    assert api.get("/api/browser/capabilities").json()["available"] is False
    assert api.post("/api/browser/runs", json={"urls": ["https://example.com/"]}).status_code == 503
    assert api.post("/api/browser/runs", json={"urls": ["http://127.0.0.1/"]}).status_code == 422
    assert (
        api.post("/api/browser/runs", json={"urls": ["https://example.com/"], "shell": "evil"}).status_code
        == 422
    )
    with session_factory()() as session:
        assert not list(session.scalars(select(Run)))


def test_normal_queue_records_screenshots_text_audit_and_portable_paths(monkeypatch):
    fake_runner(monkeypatch)
    api = TestClient(app)
    response = api.post("/api/browser/runs", json={"urls": ["https://example.com/"]})
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["effective_permissions"] == ["browser", "network_read"]
    run_worker()
    result = api.get("/api/runs/" + queued["id"]).json()
    assert result["status"] == "succeeded", result
    page = result["metadata"]["browser"]["pages"][0]
    assert page["text"] == "Visible JavaScript text" and page["request_count"] == 1
    artifacts = api.get("/api/artifacts?run_id=" + queued["id"]).json()
    assert {row["type"] for row in artifacts} == {"image", "json"}
    assert all(not row["relative_path"].startswith("/") for row in artifacts)
    image = api.get("/api/artifacts/" + page["screenshot_artifact_id"] + "/file")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    audit = next(row for row in artifacts if row["type"] == "json")
    assert (
        api.get("/api/artifacts/" + audit["id"] + "/file").json()["pages"][0]["requests"][0]["method"]
        == "GET"
    )


@pytest.mark.parametrize("mode", ["failed", "canceled", "uncertain", "revoked"])
def test_non_success_never_adopts_results(monkeypatch, mode):
    _, cancel = fake_runner(
        monkeypatch,
        exit_code=1 if mode == "failed" else 0,
        canceled=mode == "canceled",
        uncertain=mode == "uncertain",
    )
    api = TestClient(app)
    queued = api.post("/api/browser/runs", json={"urls": ["https://example.com/"]}).json()
    if mode == "revoked":
        with session_factory()() as session:
            row = session.get(Run, queued["id"])
            row.effective_permissions = ["network_read"]
            session.commit()
    run_worker()
    result = api.get("/api/runs/" + queued["id"]).json()
    assert (
        result["status"]
        == {"failed": "failed", "canceled": "canceled", "uncertain": "interrupted", "revoked": "failed"}[mode]
    )
    assert api.get("/api/artifacts?run_id=" + queued["id"]).json() == []
    if mode == "canceled":
        assert cancel == [queued["id"]]


def test_browser_agent_requires_saved_urls_and_publishes_host_step(monkeypatch):
    monkeypatch.setattr(browser, "available", lambda: {"available": True})
    api = TestClient(app)
    base = {
        "name": "Page reviewer",
        "goal": "Review this site",
        "model": "fake-local",
        "tools": ["browser"],
        "enabled": True,
    }
    assert api.post("/api/agents", json=base).status_code == 422
    response = api.post("/api/agents", json={**base, "fetch_urls": ["https://example.com/"]})
    assert response.status_code == 201, response.text
    agent = response.json()
    assert set(agent["effective_permissions"]) == {"browser", "network_read"}
    parent = api.post(
        "/api/agents/" + agent["id"] + "/run", json={"expected_updated_at": agent["updated_at"]}
    )
    assert parent.status_code == 202, parent.text
    run_worker()
    with session_factory()() as session:
        child = session.scalar(
            select(Run).where(Run.parent_run_id == parent.json()["id"], Run.executor_type == "browser")
        )
        assert child and child.execution_target == "host" and child.parameters["tool"] == "browser"
        assert browser.BrowserExecutor().payload(child)["urls"] == ["https://example.com/"]
        child.parameters = {**child.parameters, "deadline_at": (utcnow() - timedelta(seconds=1)).isoformat()}
        with pytest.raises(ValueError, match="runtime limit"):
            browser.BrowserExecutor().payload(child)


def test_mismatched_result_or_source_path_never_adopts(monkeypatch):
    reports, _ = fake_runner(monkeypatch)
    api = TestClient(app)
    queued = api.post("/api/browser/runs", json={"urls": ["https://example.com/"]}).json()
    # Change the report response after dispatch, before the executor adopts it.
    original = browser.BrowserExecutor.report

    def report(self, runner, run_id):
        result = copy.deepcopy(original(self, runner, run_id))
        result["pages"][0]["screenshot_path"] = "../../secret.png"
        return result

    monkeypatch.setattr(browser.BrowserExecutor, "report", report)
    run_worker()
    assert reports
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "failed"
    assert api.get("/api/artifacts?run_id=" + queued["id"]).json() == []


@pytest.mark.parametrize("scheduled", [False, True])
def test_agent_browser_reports_reviewed_snapshot_and_own_memory(monkeypatch, scheduled):
    from app.local_provider import LocalChatProvider
    from app.models import Agent, MemoryEntry
    from app.schedule import scheduler_tick

    fake_runner(monkeypatch)
    messages = []

    async def stream(self, **params):
        messages.append(params["messages"])
        yield "# Reviewed page\n\nVisible JavaScript text"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    response = api.post(
        "/api/agents",
        json={
            "name": "Browser reviewer",
            "goal": "Summarize reviewed pages",
            "model": "fake-local",
            "tools": ["browser", "remember_workflow"],
            "enabled": True,
            "fetch_urls": ["https://example.com/"],
            "trigger": "interval" if scheduled else "manual",
            "interval_seconds": 60 if scheduled else None,
        },
    )
    assert response.status_code == 201, response.text
    agent = response.json()
    if scheduled:
        with session_factory()() as session:
            session.get(Agent, agent["id"]).next_run_at = utcnow() - timedelta(seconds=1)
            session.commit()
            run_id = scheduler_tick(session)[0]
            session.commit()
    else:
        run_id = api.post(
            "/api/agents/" + agent["id"] + "/run", json={"expected_updated_at": agent["updated_at"]}
        ).json()["id"]
    with session_factory()() as session:
        session.get(Agent, agent["id"]).fetch_urls = ["https://example.com/later"]
        session.commit()
        for _ in range(10):
            if tick(session, "browser-agent-test") is None:
                break
        assert session.get(Run, run_id).status == "succeeded"
        children = list(session.scalars(select(Run).where(Run.parent_run_id == run_id)))
        browser_run = next(row for row in children if row.executor_type == "browser")
        report = next(row for row in children if row.executor_type == "agent")
        assert report.metadata_json["browser"]["urls"] == ["https://example.com/"]
        assert "Visible JavaScript text" in str(messages) and "untrusted" in str(messages)
        assert "requests" not in report.parameters["tool_context"][0]["result"]["pages"][0]
        memory = session.scalar(select(MemoryEntry).where(MemoryEntry.source_run_id == browser_run.id))
        assert memory.scope == "agent" and memory.scope_id == agent["id"]
    assert "browser.page.completed" in api.get("/api/runs/" + browser_run.id + "/stream").text


def test_worker_releases_transaction_before_stopping_heartbeat(monkeypatch):
    from contextlib import contextmanager

    from app import engine

    fake_runner(monkeypatch)
    api = TestClient(app)
    api.post("/api/browser/runs", json={"urls": ["https://example.com/"]})
    observed = []

    @contextmanager
    def lease(run_id, worker_id):
        yield
        # A lease renewal uses another session. It must not wait for a transaction
        # that the worker would commit only after joining that renewal thread.
        with session_factory()() as renewal:
            observed.append(renewal.get(Run, run_id).status)

    monkeypatch.setattr(engine, "keep_lease", lease)
    run_worker()
    assert observed == ["succeeded"]


def test_uncertain_container_cleanup_overrides_cancellation(monkeypatch):
    fake_runner(monkeypatch, uncertain=True, canceled=True)
    api = TestClient(app)
    run_id = api.post("/api/browser/runs", json={"urls": ["https://example.com/"]}).json()["id"]
    run_worker()
    result = api.get("/api/runs/" + run_id).json()
    assert result["status"] == "interrupted"
    assert result["metadata"]["cleanup_requires_inspection"]
    assert api.get("/api/artifacts?run_id=" + run_id).json() == []


def test_stale_canceled_browser_never_confirms_unknown_container_cleanup(monkeypatch):
    from app.recovery import recover_stale

    fake_runner(monkeypatch, uncertain=True)
    api = TestClient(app)
    run_id = api.post("/api/browser/runs", json={"urls": ["https://example.com/"]}).json()["id"]
    with session_factory()() as session:
        row = session.get(Run, run_id)
        row.status = "cancel_requested"
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert recover_stale(session) == [run_id]
        assert row.status == "interrupted" and row.metadata_json["cleanup_requires_inspection"]
