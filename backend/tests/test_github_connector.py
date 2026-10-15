import copy

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.runner_client import RunnerClient
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


def fake_runner(monkeypatch, *, canceled=False, uncertain=False, mismatch=False):
    reports = {}

    def request(self, method, path, payload=None):
        if path == "/v1/runs/github-read":
            rid = payload["run_id"]
            assert set(payload["permissions"]) == {"github_read", "network_read"}
            reports[rid] = {
                "run_id": rid,
                "repository": "other/repo" if mismatch else payload["repository"],
                "captured_at": utcnow().isoformat(),
                "project": {
                    "name": payload["repository"],
                    "url": "https://github.com/owner/repo",
                    "default_branch": "develop",
                    "private": True,
                },
                "issues": [],
                "pull_requests": [],
            }
            if canceled:
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, rid))
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
                "status": "interrupted" if uncertain else "canceled" if canceled else "exited",
                "exit_code": None if uncertain else 0,
                "stdout": "",
                "stderr": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }
        if path == "/v1/process/cancel":
            return {}
        if path.endswith("/report"):
            return reports[path.split("/")[-2]]
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(RunnerClient, "request", request)
    return reports


def create(client):
    result = client.post(
        "/api/connectors",
        json={"kind": "github", "name": "Our project", "key": "our-github", "repository": "owner/repo"},
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def work():
    with session_factory()() as session:
        tick(session, "github-test")


def test_read_snapshot_persists_history_and_survives_refresh_failure(monkeypatch):
    fake_runner(monkeypatch)
    with TestClient(app) as client:
        cid = create(client)
        check = client.post(f"/api/connectors/{cid}/check")
        assert check.status_code == 202, check.text
        run = check.json()
        assert run["execution_target"] == "host" and run["effective_permissions"] == [
            "network_read",
            "github_read",
        ]
        assert client.post(f"/api/connectors/{cid}/check").status_code == 409
        assert client.patch(f"/api/connectors/{cid}", json={"repository": "other/repo"}).status_code == 409
        work()
        result = client.get(f"/api/connectors/{cid}/snapshot").json()
        assert result["connector"]["status"] == "ready"
        snapshot = copy.deepcopy(result["snapshot"])
        assert snapshot["repository"] == "owner/repo"
        artifact = client.get("/api/artifacts/" + snapshot["artifact_id"]).json()
        assert artifact["type"] == "json" and not artifact["relative_path"].startswith("/")
        fake_runner(monkeypatch, mismatch=True)
        client.post(f"/api/connectors/{cid}/check")
        work()
        assert client.get(f"/api/connectors/{cid}/snapshot").json()["snapshot"] == snapshot
        assert client.get(f"/api/connectors/{cid}").json()["status"] == "failed"
        assert client.delete(f"/api/connectors/{cid}").status_code == 204
        assert client.get("/api/artifacts/" + snapshot["artifact_id"]).status_code == 200


@pytest.mark.parametrize(
    ("flags", "status"),
    [({"canceled": True}, "canceled"), ({"uncertain": True}, "interrupted"), ({"mismatch": True}, "failed")],
)
def test_canceled_uncertain_and_mismatched_jobs_never_adopt_snapshots(monkeypatch, flags, status):
    fake_runner(monkeypatch, **flags)
    with TestClient(app) as client:
        cid = create(client)
        rid = client.post(f"/api/connectors/{cid}/check").json()["id"]
        work()
        result = client.get("/api/runs/" + rid).json()
        assert result["status"] == status, result
        assert client.get(f"/api/connectors/{cid}/snapshot").json()["snapshot"] is None
        assert client.get("/api/artifacts?run_id=" + rid).json() == []


@pytest.mark.parametrize(
    "extra",
    [
        {"url": "https://evil.example/"},
        {"secret": "private"},
        {"secret_ref": "env:GH_TOKEN"},
        {"repository": "owner/../repo"},
        {"repository": "-owner/repo"},
    ],
)
def test_invalid_configuration_never_queues_or_copies_credentials(extra):
    with TestClient(app) as client:
        result = client.post(
            "/api/connectors",
            json={
                "kind": "github",
                "name": "Repo",
                "key": "repo-github",
                "repository": "owner/repo",
                **extra,
            },
        )
        assert result.status_code == 422, result.text
        with session_factory()() as session:
            assert list(session.scalars(select(Run))) == []
