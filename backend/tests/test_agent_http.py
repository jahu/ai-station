"""Saved API authority, credential isolation and the normal agent/data workflow."""

import asyncio
import json
import time
from urllib.parse import quote
from uuid import uuid4

import pytest
from app.agent_http import execute_source, verified_result
from app.agent_schema import AgentSettings
from app.agent_tools import calling_tools, parse_tool_call
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.models import Artifact, Run
from app.providers import ProviderError
from app.runs import create_run, create_task, request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agents import create, drain, run_now, workflow_step
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment

TOKEN = "fixture-token+/secret"


def connection(api, **extra):
    response = api.post(
        "/api/connectors",
        json={
            "key": "test-api",
            "name": "Numbers API",
            "url": "https://data.example.com/numbers",
            "secret": TOKEN,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def scope(row):
    return {"connector_id": row["id"], "connector_revision": row["http_policy_revision"]}


def saved_agent(api, row, **extra):
    return create(api, tools=["http_connector"], http=scope(row), enabled=True, **extra)


@pytest.fixture
def network(monkeypatch):
    calls = []

    async def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "url": url,
            "status": 200,
            "content_type": "application/json",
            "text": json.dumps({"values": [12, 15], "echo": TOKEN, "escaped": quote(TOKEN, safe="")}),
            "truncated": False,
            "untrusted": True,
        }

    monkeypatch.setattr("app.agent_http.fetch_public", fetch)
    return calls


def test_activation_requires_operator_scope_and_legacy_identity():
    legacy = AgentSettings(name="Old", goal="Report")
    assert "http" not in legacy.model_dump(mode="json")
    assert AgentSettings.model_validate(legacy.model_dump()).model_dump() == legacy.model_dump()
    api = TestClient(app)
    draft = create(api, tools=["http_connector"])
    blocked = api.post(
        f"/api/agents/{draft['id']}/enabled",
        json={"enabled": True, "expected_updated_at": draft["updated_at"]},
    )
    assert blocked.status_code == 422 and "saved HTTP" in blocked.text
    row = connection(api)
    assert (
        api.post("/api/agents", json={"name": "Wrong", "goal": "read", "http": scope(row)}).status_code == 422
    )


def test_report_uses_frozen_connection_and_scrubs_all_echoes(network, monkeypatch):
    received = []

    async def stream(self, **kw):
        received.append(kw)
        yield "The observed values are 12 and 15."

    monkeypatch.setattr("app.local_provider.LocalChatProvider.stream", stream)
    api = TestClient(app)
    row = connection(api)
    agent = saved_agent(api, row, tool_calling="bounded")
    queued = run_now(api, agent)
    with session_factory()() as s:
        drain(s)
    source = workflow_step(api, queued["id"], "http_connector")
    report = workflow_step(api, queued["id"], "report")
    assert source["status"] == report["status"] == "succeeded", report
    assert network == [
        ("https://data.example.com/numbers", {"extra_headers": {"Authorization": "Bearer " + TOKEN}})
    ]
    assert "12" in str(received) and "[redacted]" in str(received)
    dumped = json.dumps([source, report, received], default=str)
    assert TOKEN not in dumped and quote(TOKEN, safe="") not in dumped
    with session_factory()() as s:
        for artifact in s.scalars(select(Artifact)):
            assert TOKEN.encode() not in (get_settings().data_dir / artifact.relative_path).read_bytes()
        saved = s.get(Run, source["id"])
        definition = AgentSettings.model_validate(saved.parameters["definition"])
        verified_result(s, saved, definition.http)
        saved.metadata_json = {
            **saved.metadata_json,
            "observation": {**saved.metadata_json["observation"], "pages": []},
        }
        with pytest.raises(ValueError, match="differs"):
            verified_result(s, saved, definition.http)
    exposed = calling_tools(AgentSettings.model_validate(report["parameters"]["definition"]))
    assert exposed[0]["function"]["parameters"]["properties"] == {}


@pytest.mark.parametrize(
    "patch",
    [
        {"url": "https://other.example.com/api"},
        {"enabled": False},
        {"secret": "new-token"},
        {"secret_ref": "env:ANOTHER_HTTP_KEY"},
        {"clear_secret": True},
    ],
)
def test_authority_edit_revokes_saved_agent_before_network(network, patch):
    api = TestClient(app)
    row = connection(api)
    agent = saved_agent(api, row)
    queued = run_now(api, agent)
    changed = api.patch("/api/connectors/" + row["id"], json=patch)
    assert changed.status_code == 200
    assert changed.json()["http_policy_revision"] != row["http_policy_revision"]
    with session_factory()() as s:
        drain(s)
    parent = api.get("/api/runs/" + queued["id"]).json()
    assert parent["status"] == "failed", parent
    assert not network


def test_health_and_name_do_not_revoke_but_secret_rotation_always_does(network):
    api = TestClient(app)
    row = connection(api)
    changed = api.patch("/api/connectors/" + row["id"], json={"name": "New label"}).json()
    assert changed["http_policy_revision"] == row["http_policy_revision"]
    # Health changes updated_at; policy identity must remain independent of it.
    from app.db import utcnow
    from app.models import Connector

    with session_factory()() as s:
        dbrow = s.get(Connector, row["id"])
        dbrow.health, dbrow.updated_at = "healthy", utcnow()
        s.commit()
    assert (
        api.get("/api/connectors/" + row["id"]).json()["http_policy_revision"] == row["http_policy_revision"]
    )
    assert (
        api.patch("/api/connectors/" + row["id"], json={"secret": TOKEN}).json()["http_policy_revision"]
        != row["http_policy_revision"]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"url": "https://evil.example.com/"},
        {"connector_id": str(uuid4())},
        {"headers": {"Authorization": "invented"}},
    ],
)
def test_model_cannot_choose_api_target_or_headers(arguments):
    definition = AgentSettings(name="Read", goal="Read API", tools=["http_connector"])
    with pytest.raises(ValueError, match="model-selected"):
        parse_tool_call(definition, {"name": "http_connector", "arguments": json.dumps(arguments)})


def test_saved_scope_clears_when_tool_removed():
    api = TestClient(app)
    row = connection(api)
    agent = saved_agent(api, row)
    payload = {key: agent[key] for key in AgentSettings.model_fields if key in agent}
    payload.update(tools=[], http=None, enabled=False, expected_updated_at=agent["updated_at"])
    updated = api.put("/api/agents/" + agent["id"], json=payload)
    assert updated.status_code == 200, updated.text
    from app.models import Agent

    with session_factory()() as s:
        assert s.get(Agent, agent["id"]).http is None


@pytest.mark.parametrize("mode", ["stop", "timeout", "revoke", "error"])
def test_inflight_source_stop_expiry_and_revision_change(network, monkeypatch, mode):
    api = TestClient(app)
    row = connection(api)
    definition = AgentSettings(name="Read", goal="Read", tools=["http_connector"], http=scope(row))

    async def fetch(url, **kwargs):
        if mode == "error":
            raise RuntimeError("echo " + TOKEN)
        if mode == "revoke":
            with session_factory()() as other:
                from app.models import Connector

                current = other.get(Connector, row["id"])
                current.enabled = False
                other.commit()
        if mode == "stop":
            with session_factory()() as other:
                request_cancel(other, other.get(Run, run_id))
                other.commit()
        await asyncio.sleep(0.1)
        return {"url": url, "status": 200, "text": "data"}

    monkeypatch.setattr("app.agent_http.fetch_public", fetch)
    with session_factory()() as s:
        task = create_task(s, title="Source", prompt="Read", capability="agent.step")
        run = create_run(
            s,
            task,
            run_type="agent",
            capability="agent.step",
            executor_type="agent_tool",
            execution_target="container",
            permissions=["network_read", "http_connector_read"],
            parameters={},
        )
        run.status = "running"
        s.commit()
        run_id = run.id
        if mode == "stop":
            assert asyncio.run(execute_source(s, run, definition.http, time.monotonic() + 2)) is None
        else:
            with pytest.raises(
                (ValueError, ProviderError), match="changed|unavailable|limit|failed"
            ) as error:
                asyncio.run(
                    execute_source(
                        s, run, definition.http, time.monotonic() + (0.02 if mode == "timeout" else 2)
                    )
                )
            assert TOKEN not in str(error.value)
        assert list(s.scalars(select(Artifact))) == []


def test_connected_api_data_reaches_offline_python_without_credential_authority(data_environment, network):
    from test_agent_research_data import complete, launch

    api = TestClient(app)
    row = connection(api)
    _, parent = launch(
        api, data_environment, tools=["python_data", "http_connector"], fetch_urls=[], http=scope(row)
    )
    rows = complete(parent)
    final = next(r for r in rows if r.executor_type == "agent_data_result")
    assert final.status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
    python = next(r for r in rows if r.executor_type == "python")
    assert "http_connector_read" not in python.effective_permissions
    source_input = python.parameters["inputs"][0]
    with session_factory()() as s:
        artifact = s.get(Artifact, source_input["artifact_id"])
        data = json.loads((get_settings().data_dir / artifact.relative_path).read_bytes())
        assert data["observations"][0]["tool"] == "http_connector"
        body = data["observations"][0]["result"]["pages"][0]["text"]
        assert json.loads(body)["values"] == [12, 15] and TOKEN not in body
        source = next(r for r in rows if r.parameters.get("tool") == "http_connector")
        saved = s.get(Run, source.id)
        definition = AgentSettings.model_validate(saved.parameters["definition"])
        s.commit()
        api.patch("/api/connectors/" + row["id"], json={"enabled": False})
        verified_result(s, saved, definition.http, for_execution=False)
        with pytest.raises(ValueError, match="unavailable"):
            verified_result(s, saved, definition.http)


def test_changed_connection_is_visible_and_agent_can_still_be_paused():
    api = TestClient(app)
    row = connection(api)
    agent = saved_agent(api, row)
    assert api.patch("/api/connectors/" + row["id"], json={"enabled": False}).status_code == 200
    stale = api.get("/api/agents/" + agent["id"]).json()
    assert stale["http_readiness"]["ready"] is False
    assert stale["http"] == scope(row)
    paused = api.post(
        "/api/agents/" + agent["id"] + "/enabled",
        json={"enabled": False, "expected_updated_at": stale["updated_at"]},
    )
    assert paused.status_code == 200 and paused.json()["enabled"] is False
    reenable = api.post(
        "/api/agents/" + agent["id"] + "/enabled",
        json={"enabled": True, "expected_updated_at": paused.json()["updated_at"]},
    )
    assert reenable.status_code == 422


@pytest.mark.parametrize("change", ["missing_secret", "deleted", "plaintext"])
def test_unavailable_or_insecure_connection_fails_before_request(network, change):
    api = TestClient(app)
    row = connection(api, **({"url": "http://data.example.com/numbers"} if change == "plaintext" else {}))
    if change == "deleted":
        assert api.delete("/api/connectors/" + row["id"]).status_code == 204
    if change == "missing_secret":
        from app.models import Connector
        from app.secrets import clear_secret_file

        with session_factory()() as s:
            clear_secret_file(s.get(Connector, row["id"]).secret_ref)
    failed = api.post(
        "/api/agents",
        json={
            "name": "API",
            "goal": "Read",
            "model": "fake-local",
            "enabled": True,
            "tools": ["http_connector"],
            "http": scope(row),
        },
    )
    assert failed.status_code == 422
    assert not network


def test_health_check_also_redacts_echoed_credentials(network):
    api = TestClient(app)
    row = connection(api)
    queued = api.post("/api/connectors/" + row["id"] + "/check")
    assert queued.status_code == 202
    with session_factory()() as s:
        drain(s)
    result = api.get("/api/runs/" + queued.json()["id"]).json()
    assert result["status"] == "succeeded", result
    assert TOKEN not in json.dumps(result) and "[redacted]" in json.dumps(result)
    current = api.get("/api/connectors/" + row["id"]).json()
    assert current["http_policy_revision"] == row["http_policy_revision"]


def test_stop_racing_with_finished_error_consumes_secret_bearing_task_exception(network, monkeypatch):
    from app.agent_http import read_response

    api = TestClient(app)
    connection(api)
    observed = []
    with session_factory()() as s:
        task = create_task(s, title="Stop race", prompt="Read", capability="agent.step")
        run = create_run(
            s,
            task,
            run_type="agent",
            capability="agent.step",
            executor_type="agent_tool",
            execution_target="container",
            permissions=["network_read"],
            parameters={},
        )
        run.status = "running"
        s.commit()

        async def failed(*args, **kwargs):
            raise RuntimeError("transport echo " + TOKEN)

        async def completed_between_polls(tasks, **kwargs):
            # A completed Task remains unconsumed while Stop wins the next poll.
            await asyncio.sleep(0.01)
            assert next(iter(tasks)).done()
            request_cancel(s, run)
            s.commit()
            return set(), set(tasks)

        monkeypatch.setattr("app.agent_http.fetch_public", failed)
        monkeypatch.setattr("app.agent_http.asyncio.wait", completed_between_polls)

        async def scenario():
            asyncio.get_running_loop().set_exception_handler(lambda loop, context: observed.append(context))
            assert await read_response(s, run, "https://data.example.com/", "") is None
            await asyncio.sleep(0)

        asyncio.run(scenario())
    assert not observed, observed
