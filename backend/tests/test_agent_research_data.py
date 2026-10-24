"""Reviewed network observations become an owned read-only offline Python input."""

import json
from uuid import uuid4

import pytest
from app.api import app
from app.config import clear_settings_cache, get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run
from app.state import ACTIVE
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create as create_with_csv
from test_python_data_agents import data_environment as data_environment


@pytest.fixture
def sources(monkeypatch):
    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://search:8080")
    clear_settings_cache()
    calls = {"search": [], "fetch": [], "long": False}

    async def search(query):
        calls["search"].append(query)
        return {
            "query": query,
            "provider": "searxng",
            "partial": False,
            "searched_at": utcnow().isoformat(),
            "sources": [
                {
                    "id": 1,
                    "title": "Public numbers",
                    "url": "https://data.example.com/numbers",
                    "snippet": "Two observed numbers",
                }
            ],
        }

    async def fetch(url, **kwargs):
        calls["fetch"].append(url)
        data = {"values": [12, 15], "note": "x" * (6000 if calls["long"] else 1), "last_value": 15}
        return {
            "url": url,
            "status": 200,
            "content_type": "application/json",
            "text": json.dumps(data),
            "links": [],
            "truncated": False,
            "bounded": True,
            "untrusted": True,
        }

    monkeypatch.setattr("app.web_search.search", search)
    monkeypatch.setattr("app.http_fetch.fetch_public", fetch)
    return calls


def launch(api, state, **extra):
    response = api.post(
        "/api/agents",
        json={
            "name": "Public data analyst",
            "goal": "Calculate a total from reviewed public JSON",
            "model": state["model"],
            "tools": ["python_data", "http_fetch"],
            "fetch_urls": ["https://data.example.com/numbers"],
            "enabled": True,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["data"] == {"input_artifact_ids": [], "max_repairs": 1} and agent["data_readiness"]["ready"]
    response = api.post(
        "/api/agents/" + agent["id"] + "/run", json={"expected_updated_at": agent["updated_at"]}
    )
    assert response.status_code == 202, response.text
    return agent, response.json()


def step():
    with session_factory()() as s:
        return tick(s, "research-data-worker")


def complete(parent):
    for _ in range(30):
        if step() is None:
            break
    with session_factory()() as s:
        rows = list(
            s.scalars(select(Run).where(Run.task_id == parent["task_id"]).order_by(Run.created_at, Run.id))
        )
        assert not any(r.status in ACTIVE for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        return rows


@pytest.mark.parametrize(
    "tools",
    [
        ["python_data", "http_fetch"],
        ["python_data", "web_search"],
        ["search_pages", "python_data", "http_fetch", "web_search"],
    ],
)
def test_public_only_workflow_freezes_full_sources_in_approved_python_input(data_environment, sources, tools):
    sources["long"] = True
    with TestClient(app) as api:
        _, parent = launch(api, data_environment, tools=tools, search_query="public numbers")
        rows = complete(parent)
        final = next(r for r in rows if r.executor_type == "agent_data_result")
        assert final.status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
        python = next(r for r in rows if r.executor_type == "python")
        generation = next(r for r in rows if r.executor_type == "agent_data_generate")
        assert len(python.parameters["input_artifact_ids"]) == 1
        assert not any(r.executor_type == "local_proposal" for r in rows)
        source_input = python.parameters["inputs"][0]
        with session_factory()() as s:
            artifact = s.get(Artifact, source_input["artifact_id"])
            raw = (get_settings().data_dir / artifact.relative_path).read_bytes()
            payload = json.loads(raw)
            handoff = s.get(Run, artifact.run_id)
            assert handoff.executor_type == "agent_page_coding" and handoff.status == "succeeded"
            assert len(artifact.parent_artifact_ids) == len(payload["observations"])
            assert final.metadata_json["data_result"]["input_artifact_ids"] == [artifact.id]
            script = s.get(Artifact, generation.metadata_json["script_artifact_id"])
            assert script.parent_artifact_ids == [artifact.id]
            expected = [name for name in ("web_search", "search_pages", "http_fetch") if name in tools]
            assert [item["tool"] for item in payload["observations"]] == expected
            if "http_fetch" in tools:
                body = next(
                    x["result"]["pages"][0]["text"]
                    for x in payload["observations"]
                    if x["tool"] == "http_fetch"
                )
                assert json.loads(body)["last_value"] == 15 and len(body) > 6000
        request = json.loads(generation.parameters["messages"][1]["content"])
        research = request["research"]
        assert research["input_name"] == source_input["artifact_id"] + ".json"
        assert request["runtime"]["input_map"] == {
            research["input_name"]: "/inputs/" + research["input_name"]
        }
        if "http_fetch" in tools:
            assert (
                len(
                    next(
                        x["result"]["pages"][0]["text"]
                        for x in research["observations"]
                        if x["tool"] == "http_fetch"
                    )
                )
                <= 1000
            )
        assert len(data_environment["jobs"]) == 1


def test_uploaded_file_and_public_input_keep_both_input_lineages(data_environment, sources):
    with TestClient(app) as api:
        _, parent, artifact, original = create_with_csv(
            api,
            data_environment,
            tools=["python_data", "http_fetch"],
            fetch_urls=["https://data.example.com/numbers"],
        )
        rows = complete(parent)
        final = next(r for r in rows if r.executor_type == "agent_data_result")
        assert final.status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
        python = next(r for r in rows if r.executor_type == "python")
        assert (
            python.parameters["input_artifact_ids"][0] == artifact["id"]
            and len(python.parameters["input_artifact_ids"]) == 2
        )
        assert api.get("/api/artifacts/" + artifact["id"] + "/file").content == original


def test_python_repair_reuses_the_same_snapshot_without_another_public_read(data_environment, sources):
    data_environment["program_failures"] = 1
    with TestClient(app) as api:
        _, parent = launch(api, data_environment)
        rows = complete(parent)
        results = [r for r in rows if r.executor_type == "agent_data_result"]
        assert results[-1].status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
        assert sources["fetch"] == ["https://data.example.com/numbers"]
        jobs = [r for r in rows if r.executor_type == "python"]
        assert len(jobs) == 2
        assert (
            jobs[0].parameters["inputs"] == jobs[1].parameters["inputs"]
            and jobs[0].parameters["agent_coding_deadline"] == jobs[1].parameters["agent_coding_deadline"]
        )
        assert results[-1].metadata_json["data_result"]["attempt"] == 1


def test_ordinary_data_scope_still_requires_files_and_other_execution_families_cannot_mix():
    from app.agent_schema import AgentSettings
    from app.data_schema import AgentDataScope

    for value in [{}, {"input_artifact_ids": []}]:
        with pytest.raises(ValueError):
            AgentDataScope.model_validate(value)
        with pytest.raises(ValueError):
            AgentSettings(name="Data", goal="Analyze", tools=["python_data"], data=value)
    for tool in [
        "coding_local",
        "coding_cursor",
        "coding_codex",
        "create_media",
        "market_watch",
        "memory_search",
    ]:
        with pytest.raises(ValueError):
            AgentSettings(name="No expansion", goal="Analyze", tools=["python_data", tool])
    with pytest.raises(ValueError):
        AgentSettings(
            name="Too many",
            goal="Analyze",
            tools=["python_data", "http_fetch"],
            fetch_urls=["https://data.example.com/numbers"],
            data={"input_artifact_ids": [str(uuid4()) for _ in range(8)]},
        )


def queued_generation(api, state):
    _, parent = launch(api, state)
    for _ in range(12):
        with session_factory()() as s:
            run = s.scalar(
                select(Run).where(
                    Run.task_id == parent["task_id"], Run.executor_type == "agent_data_generate"
                )
            )
            if run:
                return parent, run.id
        assert step() is not None
    raise AssertionError("No queued data generation")


@pytest.mark.parametrize(
    "change",
    [
        "snapshot_bytes",
        "snapshot_hash",
        "snapshot_trash",
        "source_bytes",
        "source_observation",
        "foreign_task",
        "handoff_owner",
        "handoff_child",
        "source_permission",
        "scope_permissions",
        "snapshot_lineage",
        "source_deadline",
    ],
)
def test_changed_or_unreviewed_sources_never_reach_model_or_python(data_environment, sources, change):
    from app.runs import create_task

    with TestClient(app) as api:
        parent, gid = queued_generation(api, data_environment)
        with session_factory()() as s:
            generation = s.get(Run, gid)
            scope = generation.parameters["agent_data"]
            workflow = s.get(Run, scope["workflow_run_id"])
            receipt = scope["data_research"]
            handoff = s.get(Run, receipt["context_run_id"])
            snapshot = s.get(Artifact, receipt["input"]["artifact_id"])
            source = s.scalar(
                select(Run).where(Run.parent_run_id == workflow.id, Run.executor_type == "agent_tool")
            )
            artifact = s.get(Artifact, source.metadata_json["observation"]["artifact_id"])
            if change == "snapshot_bytes":
                (get_settings().data_dir / snapshot.relative_path).write_text('{"observations":[]}')
            elif change == "snapshot_hash":
                snapshot.sha256 = "0" * 64
            elif change == "snapshot_trash":
                snapshot.trashed_at = utcnow()
            elif change == "source_bytes":
                (get_settings().data_dir / artifact.relative_path).write_text('{"injected":true}')
            elif change == "source_observation":
                source.metadata_json = {
                    **source.metadata_json,
                    "observation": {
                        **source.metadata_json["observation"],
                        "urls": ["https://other.example.com/"],
                    },
                }
            elif change == "foreign_task":
                source.task_id = create_task(s, title="Other", prompt="Other scope", capability="agent").id
            elif change == "handoff_owner":
                handoff.parent_run_id = parent["id"]
            elif change == "handoff_child":
                handoff.metadata_json = {**handoff.metadata_json, "child_run_id": str(uuid4())}
            elif change == "source_permission":
                workflow.effective_permissions = [
                    p for p in workflow.effective_permissions if p != "network_read"
                ]
            elif change == "scope_permissions":
                generation.effective_permissions = [*generation.effective_permissions, "external_ai"]
            elif change == "snapshot_lineage":
                snapshot.parent_artifact_ids = []
            elif change == "source_deadline":
                source.parameters = {**source.parameters, "deadline_at": "2099-01-01T00:00:00+00:00"}
            s.commit()
        rows = complete(parent)
        generation = next(r for r in rows if r.id == gid)
        assert generation.status == "failed", [(r.executor_type, r.status, r.error_message) for r in rows]
        assert data_environment["calls"] == 0 and not data_environment["jobs"]
        assert sources["fetch"] == ["https://data.example.com/numbers"]


@pytest.mark.parametrize("before", ["sources", "handoff", "generation"])
def test_stop_prevents_later_research_or_code(data_environment, sources, before):
    with TestClient(app) as api:
        _, parent = launch(api, data_environment)
        for _ in range(12):
            with session_factory()() as s:
                rows = list(s.scalars(select(Run).where(Run.task_id == parent["task_id"])))
                wanted = next(
                    (
                        r
                        for r in rows
                        if r.status == "queued"
                        and (
                            r.executor_type == "agent_tool"
                            if before == "sources"
                            else r.executor_type == "agent_page_coding"
                            if before == "handoff"
                            else r.executor_type == "agent_data_generate"
                        )
                    ),
                    None,
                )
            if wanted and (
                before != "handoff"
                or any(r.executor_type == "agent_tool" and r.status == "succeeded" for r in rows)
            ):
                break
            assert step() is not None
        assert wanted is not None
        response = api.post("/api/runs/" + parent["id"] + "/cancel")
        assert response.status_code == 200
        complete(parent)
        assert data_environment["calls"] == 0 and not data_environment["jobs"]
        assert bool(sources["fetch"]) == (before != "sources")


def test_approval_precedes_private_workspace_and_public_requests(data_environment, sources):
    with TestClient(app) as api:
        _, parent = launch(api, data_environment, require_approval=True)
        assert parent["status"] == "waiting_for_approval" and step() is None
        assert not sources["fetch"] and not data_environment["calls"]
        with session_factory()() as s:
            assert not list(s.scalars(select(Run).where(Run.parent_run_id == parent["id"])))


def test_assisted_schema_keeps_conversation_data_inputs_strict():
    from app.agent_schema import AgentSettings
    from app.chat import MessageBody

    value = AgentSettings(
        name="Research", goal="Analyze", tools=["python_data", "web_search"], search_query="public data"
    )
    assert value.data.model_dump() == {"input_artifact_ids": [], "max_repairs": 1}
    with pytest.raises(ValueError):
        MessageBody(content="Analyze", data={"input_artifact_ids": []})
