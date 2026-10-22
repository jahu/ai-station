import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Agent, Notice, Run, RuntimeInstance, Worktree
from app.runner_client import RunnerClient
from app.runs import request_cancel
from app.state import ACTIVE
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository

SCRIPT = "import os, json, csv\n# synthetic bounded data script\n"


@pytest.fixture
def data_environment(repository, owned_runner, monkeypatch):
    from app import agents_api, data_agents, llama, schedule
    from app.local_provider import LocalChatProvider

    model = "llamacpp:" + str(uuid4())
    with session_factory()() as session:
        instance_id = str(uuid4())
        runtime = RuntimeInstance(
            id=instance_id,
            runtime_key="llama.cpp",
            name="Fixture local model",
            ownership="managed",
            endpoint="llamacpp:" + instance_id,
            status="ready",
            metadata_json={"context_size": 131072, "model_file_id": model.removeprefix("llamacpp:")},
        )
        session.add(runtime)
        session.commit()
        iid = runtime.id
        endpoint = runtime.endpoint
    for module in [agents_api, schedule, data_agents]:
        monkeypatch.setattr(module, "model_endpoint", lambda *a, **k: endpoint)
    monkeypatch.setattr(
        llama,
        "prepare_consumer",
        lambda session, run: setattr(run, "parameters", {**run.parameters, "endpoint": endpoint}),
    )
    state = {
        "program_failures": 0,
        "bad_report": False,
        "calls": 0,
        "stop_model": False,
        "model": model,
        "jobs": {},
        "model_requests": [],
    }

    async def stream(self, **kwargs):
        state["calls"] += 1
        state["model_requests"].append(kwargs)
        assert kwargs["json_output"] and kwargs["model"] == model
        if state["stop_model"]:
            with session_factory()() as session:
                running = session.scalar(
                    select(Run).where(Run.executor_type == "agent_data_generate", Run.status == "running")
                )
                request_cancel(session, running)
                session.commit()
        yield json.dumps({"script": SCRIPT + f"# attempt {state['calls']}\n"})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    original = RunnerClient.request

    def request(self, method, path, payload=None):
        if path == "/v1/python/capabilities":
            return {"available": True, "artifact_source": True}
        if path == "/v1/llama/" + iid:
            return {"status": "ready", "alive": True, "n_ctx": 131072}
        if path == "/v1/runs/python" and method == "POST":
            with session_factory()() as session:
                run = session.get(Run, payload["run_id"])
                scope = run.parameters["agent_data"]
                tree = session.get(Worktree, scope["worktree_id"])
                from app.models import Artifact

                source = session.get(Artifact, payload["script_artifact_id"])
                script = (get_settings().data_dir / source.relative_path).read_bytes()
                (owned_runner.data_dir / tree.relative_path / payload["script_relative"]).write_bytes(script)
            assert hashlib.sha256(script).hexdigest() == payload["script_sha256"]
            stage = get_settings().data_dir / "runtime/python" / payload["run_id"]
            (stage / "inputs").mkdir(parents=True)
            (stage / "inputs/script.py").write_bytes(script)
            fail = state["program_failures"] > 0
            if fail:
                state["program_failures"] -= 1
            report = {
                "run_id": payload["run_id"],
                "project_id": payload["project_id"],
                "worktree_run_id": payload["worktree_run_id"],
                "script_sha256": payload["script_sha256"],
                "exit_code": 1 if fail else 0,
                "error": "Synthetic program failure" if fail else None,
                "succeeded": not fail,
                "outputs": [],
            }
            if not fail:
                answer = {"answer": "The total is 27.", "columns": ["Total"], "rows": [["27"]]}
                if state["bad_report"]:
                    answer["rows"] = [["999"]]
                for index, (name, data) in enumerate(
                    [("result.json", json.dumps(answer).encode()), ("result.csv", b"Total\n27\n")]
                ):
                    suffix = Path(name).suffix
                    relative = f"runtime/python/{payload['run_id']}/output-{index}{suffix}"
                    file = get_settings().data_dir / relative
                    file.write_bytes(data)
                    report["outputs"].append(
                        {
                            "name": name,
                            "relative_path": relative,
                            "size_bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        }
                    )
            state["jobs"][payload["run_id"]] = report
            return {
                "pid": 999999,
                "process_group_id": 999999,
                "runner_id": "fake-python",
                "stdout_log": "runs/fake/stdout.log",
                "stderr_log": "runs/fake/stderr.log",
            }
        if path.startswith("/v1/process/") and path.split("?")[0].split("/")[-1] in state["jobs"]:
            return {
                "alive": False,
                "status": "succeeded",
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
                "cleanup_confirmed": True,
            }
        if path.startswith("/v1/runs/python/") and path.endswith("/report"):
            return state["jobs"][path.split("/")[-2]]
        return original(self, method, path, payload)

    monkeypatch.setattr(RunnerClient, "request", request)
    return state


def create(client, state, **changes):
    source = b"Item,Total\nApple,12\nPear,15\n"
    upload = client.post("/api/data/uploads", files={"file": ("sales.csv", source, "text/csv")})
    assert upload.status_code == 201
    artifact = upload.json()
    with session_factory()() as session:
        tick(session, "data-inspection")
    body = {
        "name": "Spreadsheet helper",
        "goal": "Calculate the total",
        "model": state["model"],
        "tools": ["python_data"],
        "data": {"input_artifact_ids": [artifact["id"]], "max_repairs": 1},
        "enabled": True,
        "notification_policy": {"on_success": True, "on_failure": True},
        **changes,
    }
    response = client.post("/api/agents", json=body)
    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["data_readiness"]["ready"]
    run = client.post(
        "/api/agents/" + agent["id"] + "/run", json={"expected_updated_at": agent["updated_at"]}
    )
    assert run.status_code == 202, run.text
    return agent, run.json(), artifact, source


def finish(client, parent):
    for _ in range(14):
        with session_factory()() as session:
            rid = tick(session, "python-data-worker")
            if rid is None:
                break
    with session_factory()() as session:
        rows = list(
            session.scalars(
                select(Run).where(Run.task_id == parent["task_id"]).order_by(Run.created_at, Run.id)
            )
        )
        assert not [r.id for r in rows if r.status in ACTIVE], [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        return [(r.id, r.executor_type, r.status, r.error_message) for r in rows]


@pytest.mark.parametrize("repair", [False, True])
def test_agent_creates_workspace_and_returns_verified_answer_download_with_bounded_repair(
    data_environment, repair
):
    state = data_environment
    if repair:
        state["program_failures"] = 1
    with TestClient(app) as client:
        agent, parent, artifact, source = create(client, state)
        rows = finish(client, parent)
        with session_factory()() as session:
            final = session.scalar(
                select(Run)
                .where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
                .order_by(Run.created_at.desc(), Run.id.desc())
            )
            assert final is not None, rows
            assert final.status == "succeeded", rows
            result = final.metadata_json["data_result"]
            assert result["answer"] == "The total is 27."
            assert result["input_artifact_ids"] == [artifact["id"]] and result["attempt"] == int(repair)
            assert session.get(Agent, agent["id"]).project_id is not None
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert [(n.kind, n.title) for n in notices] == [("succeeded", "Data agent results ready")]
            assert state["calls"] == (2 if repair else 1)
            assert not any(r[1] == "local_proposal" for r in rows)
            from app.schedule import retry_view

            assert not retry_view(session, session.get(Run, parent["id"]))["allowed"]
        assert (
            client.get("/api/artifacts/" + result["download_artifact_id"] + "/file").content
            == b"Total\r\n27\r\n"
        )
        assert client.get("/api/artifacts/" + artifact["id"] + "/file").content == source


def test_stop_during_local_model_generation_never_writes_or_runs_code(data_environment):
    state = data_environment
    state["stop_model"] = True
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, state)
        rows = finish(client, parent)
        assert any(kind == "agent_data_generate" and status == "canceled" for _, kind, status, _ in rows), (
            rows
        )
        assert not state["jobs"]
        with session_factory()() as session:
            tree = session.scalar(select(Worktree))
            assert not list((get_settings().data_dir / tree.relative_path).glob("analysis-*.py"))


def test_invalid_result_is_not_successful_and_repairs_stop_at_saved_limit(data_environment):
    state = data_environment
    state["bad_report"] = True
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, state)
        rows = finish(client, parent)
        assert state["calls"] == 2, rows
        with session_factory()() as session:
            final = session.scalar(
                select(Run)
                .where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
                .order_by(Run.created_at.desc(), Run.id.desc())
            )
            assert final.status == "failed" and "match the generated CSV" in final.error_message
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert [(n.kind, n.title) for n in notices] == [("failed", "Data agent workflow failed")]


def test_missing_runtime_or_scope_blocks_activation_without_creating_runs(data_environment, monkeypatch):
    from app import data_agents

    with TestClient(app) as client:
        body = {
            "name": "Data",
            "goal": "Read a spreadsheet",
            "tools": ["python_data"],
            "model": data_environment["model"],
            "enabled": True,
        }
        assert client.post("/api/agents", json=body).status_code == 422
        assert (
            client.post("/api/agents", json={**body, "tools": ["coding_local", "python_data"]}).status_code
            == 422
        )
        monkeypatch.setattr(
            data_agents, "runtime_capability", lambda: {"available": False, "reason": "No image"}
        )
        tools = client.get("/api/agents/tools").json()
        assert not next(t for t in tools if t["name"] == "python_data")["operational"]


def test_literal_download_cells_do_not_activate_spreadsheet_formulas():
    from app.data_agents import DataResultExecutor

    assert DataResultExecutor.literal('=WEBSERVICE("https://example.com")').startswith("'=")
    assert DataResultExecutor.literal(" @SUM(A1)") == "' @SUM(A1)"
    assert DataResultExecutor.literal("-27.5") == "-27.5"


@pytest.mark.parametrize("change", ["input", "script", "attempt", "owner"])
def test_changed_scope_never_dispatches_python(data_environment, change):
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment)
        for _ in range(10):
            with session_factory()() as session:
                target = session.scalar(
                    select(Run).where(Run.executor_type == "python", Run.status == "queued")
                )
                if target:
                    values = dict(target.parameters)
                    if change == "input":
                        values["inputs"] = [{**values["inputs"][0], "sha256": "f" * 64}]
                    elif change == "script":
                        values["script_sha256"] = "f" * 64
                    elif change == "attempt":
                        values["agent_data"] = {**values["agent_data"], "attempt": 2}
                    else:
                        target.agent_id = None
                    target.parameters = values
                    session.commit()
                    rid = target.id
                    break
                tick(session, "scope-test")
        else:
            pytest.fail("Python was never queued")
        rows = finish(client, parent)
        assert not data_environment["jobs"], rows
        with session_factory()() as session:
            assert session.get(Run, rid).status in {"failed", "interrupted"}
            assert not session.scalar(select(Run.id).where(Run.executor_type == "agent_data_result"))


def test_factory_creates_disabled_data_draft_without_invented_input_scope():
    from app.factory import draft_agent

    row = draft_agent("Przeanalizuj plik Excel i policz sumę wydatków")
    assert row.tools == ["python_data"] and row.model == "auto"
    assert not row.enabled and row.data is None


def test_data_scope_migration_preserves_existing_agent():
    from alembic import command
    from app.db import alembic_config, migrate, reset_engine
    from app.factory import draft_agent

    with session_factory()() as session:
        agent = draft_agent("Existing agent", model="fixture-local")
        session.add(agent)
        session.commit()
        aid = agent.id
    reset_engine()
    command.downgrade(alembic_config(), "0026")
    migrate()
    with session_factory()() as session:
        row = session.get(Agent, aid)
        assert row.name == "Existing agent" and row.model == "fixture-local"
        assert row.data is None and not row.enabled


@pytest.mark.parametrize("size", [4096, 100000])
def test_unverified_short_context_never_generates_or_executes_code(data_environment, monkeypatch, size):
    original = RunnerClient.request

    def request(self, method, path, payload=None):
        if path.startswith("/v1/llama/"):
            return {"status": "ready", "alive": True, "n_ctx": size}
        return original(self, method, path, payload)

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment)
        rows = finish(client, parent)
        assert not data_environment["calls"] and not data_environment["jobs"], rows
        assert any(kind == "agent_data_generate" and status == "failed" for _, kind, status, _ in rows)


def test_generation_receives_exact_container_input_map_and_failed_attempt_context(data_environment):
    state = data_environment
    state["program_failures"] = 1
    with TestClient(app) as client:
        _, parent, artifact, _ = create(client, state)
        finish(client, parent)
        with session_factory()() as session:
            generation = session.scalar(
                select(Run)
                .where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_generate")
                .order_by(Run.created_at, Run.id)
            )
            from app.models import Artifact

            source = session.get(Artifact, generation.metadata_json["script_artifact_id"])
            original_code = (get_settings().data_dir / source.relative_path).read_text()
    first, repaired = state["model_requests"]
    request = json.loads(first["messages"][1]["content"])
    filename = artifact["id"] + ".csv"
    assert request["runtime"]["input_map"] == {filename: "/inputs/" + filename}
    assert request["runtime"]["output_dir"] == "/outputs"
    assert request["runtime"]["required_outputs"] == ["result.json", "result.csv"]
    assert "json.loads(os.environ" in first["messages"][0]["content"]
    assert "NOT a file" in first["messages"][0]["content"]
    retry = json.loads(repaired["messages"][1]["content"])
    assert retry["runtime"] == request["runtime"]
    assert retry["repair"]["previous_script"] == original_code
    assert "Synthetic program failure" in retry["repair"]["error"]
    assert "previous script FAILED" in repaired["messages"][0]["content"]
