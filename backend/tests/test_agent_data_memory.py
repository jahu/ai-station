"""Scoped memory composes with the ordinary offline Python agent pipeline."""

import json

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.memory import upsert_memory
from app.models import Artifact, MemoryEntry, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_research_data import complete
from test_agents import create, run_now
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_two_data_executions_use_own_memory_and_retain_only_validated_results(data_environment):
    api = TestClient(app)
    agent = create(
        api,
        name="Remembered analysis",
        goal="Analyse the numbers in my saved observations and report the total",
        model=data_environment["model"],
        tools=["python_data", "memory_search", "remember_report"],
        enabled=True,
    )
    with session_factory()() as s:
        initial = upsert_memory(
            s, scope="agent", scope_id=agent["id"], content="Observed values are 12 and 15."
        )
        upsert_memory(s, scope="agent", scope_id="another-agent", content="OTHER AGENT PRIVATE VALUE")
        upsert_memory(s, scope="global", content="UNREVIEWED GLOBAL SECRET")
        s.commit()
        initial_id = initial.id
    results = []
    for index in range(2):
        agent = api.get("/api/agents/" + agent["id"]).json()
        parent = run_now(api, agent)
        rows = complete(parent)
        final = next(r for r in rows if r.executor_type == "agent_data_result")
        assert final.status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
        source = next(r for r in rows if r.parameters.get("tool") == "memory_search")
        python = next(r for r in rows if r.executor_type == "python")
        generation = next(r for r in rows if r.executor_type == "agent_data_generate")
        assert "memory_write" not in python.effective_permissions
        assert "memory_write" not in generation.effective_permissions
        assert "memory_write" in final.effective_permissions
        with session_factory()() as s:
            original = s.get(Artifact, python.parameters["inputs"][0]["artifact_id"])
            payload = json.loads((get_settings().data_dir / original.relative_path).read_bytes())
            observation = next(item for item in payload["observations"] if item["tool"] == "memory_search")
            serialized = json.dumps(observation)
            assert initial_id in serialized and "12 and 15" in serialized
            assert "OTHER AGENT PRIVATE" not in serialized and "GLOBAL SECRET" not in serialized
            entries = list(
                s.scalars(
                    select(MemoryEntry).where(
                        MemoryEntry.scope == "agent", MemoryEntry.scope_id == agent["id"]
                    )
                )
            )
            assert len(entries) == index + 2
            retained = next(entry for entry in entries if entry.source_run_id == final.id)
            assert "The total is 27." in retained.content
            if index:
                assert "The total is 27." in serialized
            assert s.get(Run, source.id).status == "succeeded"
        results.append(final.id)
    assert len(set(results)) == 2


@pytest.mark.parametrize("change", ["disabled", "edited", "scope", "artifact", "metadata"])
def test_memory_snapshot_changes_stop_before_model_or_python(data_environment, change):
    from test_agent_research_data import step

    api = TestClient(app)
    agent = create(api, model=data_environment["model"], tools=["python_data", "memory_search"], enabled=True)
    with session_factory()() as s:
        memory = upsert_memory(s, scope="agent", scope_id=agent["id"], content="Observed numbers 12,15")
        s.commit()
        mid = memory.id
    parent = run_now(api, agent)
    for _ in range(12):
        step()
        with session_factory()() as s:
            source = s.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_tool")
            )
            if source and source.status == "succeeded":
                sid = source.id
                break
    else:
        raise AssertionError("Memory source did not finish")
    with session_factory()() as s:
        memory = s.get(MemoryEntry, mid)
        if change == "disabled":
            memory.enabled = False
        if change == "edited":
            memory.content = "New values"
        if change == "scope":
            memory.scope_id = "different-agent"
        source = s.get(Run, sid)
        if change == "artifact":
            artifact = s.scalar(select(Artifact).where(Artifact.run_id == sid))
            (get_settings().data_dir / artifact.relative_path).write_text("tampered")
        if change == "metadata":
            source.metadata_json = {
                **source.metadata_json,
                "observation": {"scope": "agent", "scope_id": agent["id"], "entries": []},
            }
        s.commit()
    rows = complete(parent)
    assert any(r.status == "failed" for r in rows)
    assert data_environment["calls"] == 0 and not data_environment["jobs"]


def test_failed_python_never_retains_a_result(data_environment):
    api = TestClient(app)
    agent = create(
        api,
        model=data_environment["model"],
        tools=["python_data", "memory_search", "remember_report"],
        enabled=True,
    )
    data_environment["program_failures"] = 5
    parent = run_now(api, agent)
    rows = complete(parent)
    assert any(r.executor_type == "agent_data_result" and r.status == "failed" for r in rows)
    with session_factory()() as s:
        assert not list(s.scalars(select(MemoryEntry).where(MemoryEntry.scope_id == agent["id"])))


def test_retention_failure_rolls_back_memory_and_does_not_repeat_python(data_environment, monkeypatch):
    api = TestClient(app)
    agent = create(
        api,
        model=data_environment["model"],
        tools=["python_data", "memory_search", "remember_report"],
        enabled=True,
    )
    from app import agent_executor

    original = agent_executor.persist_agent_memory

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic retention failure")

    monkeypatch.setattr(agent_executor, "persist_agent_memory", fail_after_write)
    rows = complete(run_now(api, agent))
    assert len(data_environment["jobs"]) == 1 and data_environment["calls"] == 1
    assert any(r.executor_type == "agent_data_result" and r.status == "failed" for r in rows)
    with session_factory()() as s:
        assert not list(s.scalars(select(MemoryEntry).where(MemoryEntry.scope_id == agent["id"])))


def test_historical_capture_remains_readable_after_memory_disable(data_environment):
    from app.agent_memory_context import verified_memory
    from app.agent_schema import AgentSettings

    api = TestClient(app)
    agent = create(api, model=data_environment["model"], tools=["python_data", "memory_search"], enabled=True)
    with session_factory()() as s:
        entry = upsert_memory(s, scope="agent", scope_id=agent["id"], content="Original observed numbers")
        s.commit()
        mid = entry.id
    rows = complete(run_now(api, agent))
    source = next(r for r in rows if r.parameters.get("tool") == "memory_search")
    with session_factory()() as s:
        entry = s.get(MemoryEntry, mid)
        entry.enabled = False
        s.commit()
        saved = s.get(Run, source.id)
        definition = AgentSettings.model_validate(saved.parameters["definition"])
        _, data, _ = verified_memory(s, saved, definition, for_execution=False, complete=True)
        assert data["entries"][0]["content"] == "Original observed numbers"
        with pytest.raises(ValueError, match="disabled"):
            verified_memory(s, saved, definition)


def test_project_memory_stays_in_reviewed_project_and_code_has_no_live_memory_authority(
    data_environment, repository
):
    from test_projects import register

    api = TestClient(app)
    project_id = register(api, repository)["id"]
    agent = create(
        api,
        model=data_environment["model"],
        project_id=project_id,
        tools=["python_data", "project_memory"],
        enabled=True,
    )
    with session_factory()() as s:
        upsert_memory(s, scope="project", scope_id=project_id, content="Reviewed project values 12 and 15")
        upsert_memory(s, scope="project", scope_id="different-project", content="PRIVATE OTHER PROJECT")
        s.commit()
    rows = complete(run_now(api, agent))
    final = next(r for r in rows if r.executor_type == "agent_data_result")
    assert final.status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
    source = next(r for r in rows if r.parameters.get("tool") == "project_memory")
    assert source.effective_permissions == ["project_memory_read"]
    python = next(r for r in rows if r.executor_type == "python")
    assert "project_memory_read" not in python.effective_permissions
    assert "PRIVATE OTHER PROJECT" not in json.dumps(data_environment["model_requests"])


@pytest.mark.parametrize("before", ["capture", "retention"])
def test_task_stop_never_saves_data_result_memory(data_environment, before):
    from test_agent_research_data import step

    api = TestClient(app)
    agent = create(
        api,
        model=data_environment["model"],
        tools=["python_data", "memory_search", "remember_report"],
        enabled=True,
    )
    parent = run_now(api, agent)
    for _ in range(20):
        with session_factory()() as s:
            rows = list(s.scalars(select(Run).where(Run.task_id == parent["task_id"])))
            wanted = next(
                (
                    r
                    for r in rows
                    if r.status == "queued"
                    and r.executor_type == ("agent_tool" if before == "capture" else "agent_data_result")
                ),
                None,
            )
        if wanted:
            break
        assert step() is not None
    assert wanted is not None
    assert api.post("/api/runs/" + parent["id"] + "/cancel").status_code == 200
    complete(parent)
    with session_factory()() as s:
        assert not list(s.scalars(select(MemoryEntry).where(MemoryEntry.scope_id == agent["id"])))


def test_local_code_uses_bounded_own_memory_before_worktree_preparation():
    from test_agent_page_coding import children, start, step

    api = TestClient(app)
    agent, parent = start(api, tools=["coding_local", "memory_search"], fetch_urls=[])
    with session_factory()() as s:
        upsert_memory(
            s, scope="agent", scope_id=agent["id"], content="Saved project decision: use a blue heading."
        )
        s.commit()
    step()
    published = children(parent["id"])
    source = next(r for r in published if r.parameters.get("tool") == "memory_search")
    handoff = next(r for r in published if r.executor_type == "agent_page_coding")
    assert step() == source.id
    assert step() == handoff.id
    prepared = next(r for r in children(parent["id"]) if r.executor_type == "worktree_prepare")
    assert "use a blue heading" in prepared.parameters["local_coding"]["guidance"]
    assert prepared.parameters["local_coding"]["context_sources"][0]["urls"] == []
    assert "external_ai" not in prepared.effective_permissions
    assert api.post("/api/runs/" + parent["id"] + "/cancel").status_code == 200
