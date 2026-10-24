"""Direct conversation scope must explicitly grant rendered data reading."""

import pytest
from app.conversation_data_schema import DataResearchSelection
from pydantic import ValidationError
from test_agent_rendered_research import rendered as rendered
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_selected_rendered_urls_use_browser_without_also_fetching_static_pages():
    scope = DataResearchSelection(fetch_urls=["https://example.com/"], render_pages=True)
    assert scope.tools() == ["browser"]
    assert scope.model_dump(mode="json")["render_pages"] is True


def test_default_static_research_preserves_legacy_receipt_serialization():
    scope = DataResearchSelection(fetch_urls=["https://example.com/"])
    assert scope.tools() == ["http_fetch"]
    assert DataResearchSelection(fetch_urls=["https://example.com/"], render_pages=False).model_dump(
        mode="json"
    ) == scope.model_dump(mode="json")
    assert scope.model_dump(mode="json") == {
        "search_query": "",
        "fetch_urls": ["https://example.com/"],
        "read_search_pages": False,
    }


@pytest.mark.parametrize(
    "value",
    [
        {"search_query": "public data", "render_pages": True},
        {"fetch_urls": ["https://example.com/"], "render_pages": "true"},
        {"fetch_urls": ["http://127.0.0.1/"], "render_pages": True},
    ],
)
def test_rendered_scope_requires_exact_explicit_public_url_permission(value):
    with pytest.raises(ValidationError):
        DataResearchSelection.model_validate(value)


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_one_conversation_send_renders_then_analyzes_without_a_persistent_agent(
    data_environment, rendered, mode
):
    from app.api import app
    from app.db import session_factory
    from app.models import Agent
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from test_conversation_research_data import drain, runs, start

    with TestClient(app) as api:
        cid, root = start(
            api, data_environment, {"fetch_urls": ["https://example.com/"], "render_pages": True}, mode=mode
        )
        assert (
            "browser" in root["effective_permissions"] and "external_ai" not in root["effective_permissions"]
        )
        drain()
        rows = runs(root["task_id"])
        source = next(r for r in rows if r.executor_type == "browser")
        result = next(r for r in rows if r.executor_type == "agent_data_result")
        assert source.agent_id is None and source.conversation_id == cid
        assert source.status == result.status == "succeeded", [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        assert source.effective_permissions == ["browser", "network_read"]
        assert len(rendered[0]) == len(data_environment["jobs"]) == 1
        python = next(r for r in rows if r.executor_type == "python")
        assert "browser" not in python.effective_permissions
        with session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(Agent)) == 0


@pytest.mark.parametrize(
    "change",
    [
        "definition",
        "permissions",
        "extra_permission",
        "manifest",
        "deadline",
        "tool",
        "scope",
        "stop",
        "expired",
    ],
)
def test_changed_or_stopped_conversation_authority_never_contacts_browser(data_environment, rendered, change):
    from datetime import timedelta

    from app.api import app
    from app.db import session_factory, utcnow
    from app.models import Run
    from app.task_control import cancel_task
    from fastapi.testclient import TestClient
    from test_conversation_research_data import drain, runs, start

    with TestClient(app) as api:
        _, root = start(api, data_environment, {"fetch_urls": ["https://example.com/"], "render_pages": True})
        source_id = queued_source(root)
        with session_factory()() as db:
            source = db.get(Run, source_id)
            if change == "definition":
                source.parameters = {
                    key: value for key, value in source.parameters.items() if key != "definition"
                }
                source.parameters = {**source.parameters, "urls": ["https://other.example.com/"]}
            elif change == "permissions":
                source.effective_permissions = ["network_read"]
            elif change == "extra_permission":
                source.effective_permissions = [*source.effective_permissions, "git_write"]
            elif change == "manifest":
                parent = db.get(Run, source.parent_run_id)
                parent.metadata_json = {**parent.metadata_json, "child_run_ids": []}
            elif change == "deadline":
                source.parameters = {
                    **source.parameters,
                    "deadline_at": (utcnow() + timedelta(seconds=900)).isoformat(),
                }
            elif change == "tool":
                source.parameters = {**source.parameters, "tool": "http_fetch"}
            elif change == "scope":
                origin = db.get(Run, root["id"])
                origin.parameters = {
                    **origin.parameters,
                    "data": {
                        **origin.parameters["data"],
                        "research": {"fetch_urls": ["https://example.com/"]},
                    },
                }
            elif change == "stop":
                cancel_task(db, source.task)
            else:
                source.parameters = {
                    **source.parameters,
                    "agent_coding_deadline": (utcnow() - timedelta(seconds=1)).isoformat(),
                }
            db.commit()
        drain()
        assert not rendered[0] and not data_environment["jobs"]
        assert not any(r.executor_type in {"agent_data_generate", "python"} for r in runs(root["task_id"]))


def queued_source(root):
    from app.db import session_factory
    from app.engine import tick
    from app.models import Run
    from sqlalchemy import select

    for _ in range(8):
        with session_factory()() as db:
            source = db.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "browser")
            )
            if source:
                assert source.status == "queued"
                return source.id
            tick(db, "rendered-conversation-publish")
    raise AssertionError("Browser source was not published")


def test_conversation_scope_is_rechecked_before_browser_artifact_adoption(
    data_environment, rendered, monkeypatch
):
    from app.api import app
    from app.db import session_factory
    from app.models import Artifact, Run
    from app.runner_client import RunnerClient
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from test_conversation_research_data import drain, runs, start

    with TestClient(app) as api:
        _, root = start(api, data_environment, {"fetch_urls": ["https://example.com/"], "render_pages": True})
        source_id = queued_source(root)
        original = RunnerClient.request

        def revoke(self, method, path, payload=None):
            if path == "/v1/runs/browser/" + source_id + "/report":
                with session_factory()() as db:
                    origin = db.get(Run, root["id"])
                    origin.effective_permissions = [p for p in origin.effective_permissions if p != "browser"]
                    db.commit()
            return original(self, method, path, payload)

        monkeypatch.setattr(RunnerClient, "request", revoke)
        drain()
        assert len(rendered[0]) == 1 and not data_environment["jobs"]
        with session_factory()() as db:
            assert (
                db.scalar(select(func.count()).select_from(Artifact).where(Artifact.run_id == source_id)) == 0
            )
        assert not any(r.executor_type in {"agent_data_generate", "python"} for r in runs(root["task_id"]))


def test_offline_followup_uses_rendered_capture_without_new_browser_permission(
    data_environment, rendered, monkeypatch
):
    from datetime import timedelta

    from app.api import app
    from app.db import utcnow
    from fastapi.testclient import TestClient
    from test_conversation_research_data import drain, runs, start

    with TestClient(app) as api:
        cid, root = start(
            api, data_environment, {"fetch_urls": ["https://example.com/"], "render_pages": True}
        )
        drain()
        original = next(r for r in runs(root["task_id"]) if r.executor_type == "python").parameters["inputs"]
        with monkeypatch.context() as clock:
            clock.setattr("app.conversation_data.utcnow", lambda: utcnow() + timedelta(days=1))
            response = api.post(
                "/api/chat/conversations/" + cid + "/messages",
                json={"content": "Now compare those observations"},
            )
        assert response.status_code == 202, response.text
        second = response.json()
        assert (
            "research" not in second["parameters"]["data"]
            and "browser" not in second["effective_permissions"]
        )
        drain()
        rows = runs(second["task_id"])
        assert all(r.status == "succeeded" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        assert next(r for r in rows if r.executor_type == "python").parameters["inputs"] == original
        assert len(rendered[0]) == 1 and len(data_environment["jobs"]) == 2


@pytest.mark.parametrize("render_pages", [False, True])
def test_receipt_replay_cannot_change_browser_grant(data_environment, rendered, render_pages):
    from uuid import uuid4

    from app.api import app
    from fastapi.testclient import TestClient
    from test_conversation_research_data import drain

    body = {
        "client_request_id": str(uuid4()),
        "selection": {"provider": "local-openai-compatible", "model": "unused", "execution_mode": "chat"},
        "content": "Calculate reviewed public numbers",
        "data": {
            "model": data_environment["model"],
            "research": {
                "fetch_urls": ["https://example.com/"],
                **({"render_pages": True} if render_pages else {}),
            },
        },
    }
    with TestClient(app) as api:
        first = api.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        same = {
            **body,
            "data": {**body["data"], "research": {**body["data"]["research"], "render_pages": render_pages}},
        }
        replay = api.post("/api/chat/turns", json=same)
        assert replay.status_code == 202 and replay.json() == first.json()
        changed = {
            **body,
            "data": {
                **body["data"],
                "research": {**body["data"]["research"], "render_pages": not render_pages},
            },
        }
        assert api.post("/api/chat/turns", json=changed).status_code == 409
        # This tests publication only; stop before any static/network/model work.
        response = api.post("/api/runs/" + first.json()["run"]["id"] + "/cancel")
        assert response.status_code == 200, response.text
        drain()
        assert not rendered[0] and not data_environment["jobs"]


def test_unavailable_browser_is_reported_before_a_task_is_enqueued(data_environment, monkeypatch):
    from app.api import app
    from app.db import session_factory
    from app.models import Run
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    monkeypatch.setattr("app.browser.available", lambda: {"available": False})
    with TestClient(app) as api:
        conv = api.post("/api/chat/conversations", json={"model": "unused", "execution_mode": "chat"}).json()
        response = api.post(
            "/api/chat/conversations/" + conv["id"] + "/messages",
            json={
                "content": "Compute public totals",
                "data": {"research": {"fetch_urls": ["https://example.com/"], "render_pages": True}},
            },
        )
        assert response.status_code == 503 and "Browser" in response.json()["detail"]
        with session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(Run)) == 0


def test_stop_during_render_cancels_owned_source_before_any_artifact_or_code(
    data_environment, rendered, monkeypatch
):
    from app.api import app
    from app.db import session_factory
    from app.models import Artifact, Run, Task
    from app.runner_client import RunnerClient
    from app.task_control import cancel_task
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from test_conversation_research_data import drain, runs, start

    with TestClient(app) as api:
        _, root = start(api, data_environment, {"fetch_urls": ["https://example.com/"], "render_pages": True})
        source_id = queued_source(root)
        original = RunnerClient.request

        def stop(self, method, path, payload=None):
            result = original(self, method, path, payload)
            if path == "/v1/runs/browser" and payload["run_id"] == source_id:
                with session_factory()() as db:
                    cancel_task(db, db.get(Task, root["task_id"]))
                    db.commit()
            return result

        monkeypatch.setattr(RunnerClient, "request", stop)
        drain()
        with session_factory()() as db:
            assert db.get(Run, source_id).status == "canceled"
            assert (
                db.scalar(select(func.count()).select_from(Artifact).where(Artifact.run_id == source_id)) == 0
            )
        assert source_id in rendered[1] and not data_environment["jobs"]
        assert not any(r.executor_type in {"agent_data_generate", "python"} for r in runs(root["task_id"]))
