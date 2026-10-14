import copy
import json
from datetime import timedelta

import pytest
from app.api import app
from app.assistant import workstation_request
from app.config import get_settings
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Conversation, Run, RunEvent, RuntimeInstance
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select

HARDWARE = {
    "gpus": [
        {
            "index": 7,
            "name": "GPU <fake>",
            "utilization": 42,
            "memory_used_mib": 512,
            "memory_total_mib": 8192,
            "temperature_c": None,
        }
    ],
    "cpu": {"utilization": None, "temperature_c": 39},
    "memory": {"used_mib": 1000, "total_mib": 8000, "available_mib": 7000},
    "disk": {"path": "/private/data", "free_bytes": 3 * 1024**3},
    "unexpected_secret": "do not persist",
}


def step():
    with session_factory()() as session:
        return tick(session, "station-test")


def setup_conversation():
    # A gone model must not prevent an observation that needs no inference.
    with session_factory()() as session:
        row = Conversation(model="llamacpp:gone", provider="missing-provider", execution_mode="orchestrator")
        session.add(row)
        session.commit()
        return row.id


def dispatch(client, cid, **options):
    result = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "Pokaż użycie GPU i RAM", **options}
    )
    assert result.status_code == 202, result.text
    assert step() == result.json()["id"]
    with session_factory()() as session:
        child = session.scalar(select(Run).where(Run.parent_run_id == result.json()["id"]))
        assert child.executor_type == "station_snapshot"
        assert child.task_id == result.json()["task_id"]
        assert child.conversation_id == cid
        assert child.effective_permissions == ["filesystem_read"]
        return child.id


@pytest.mark.parametrize(
    "prompt",
    [
        "Pokaż użycie GPU i RAM",
        "Sprawdź stan CPU",
        "Show GPU usage",
        "What is using GPU 1?",
        "Co zużywa RAM?",
    ],
)
def test_explicit_workstation_requests(prompt):
    assert workstation_request(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "What is a GPU?",
        "Explain GPU memory",
        "Create an agent that monitors GPU",
        "Generate a picture of a GPU",
    ],
)
def test_hardware_discussion_is_not_a_workstation_command(prompt):
    assert not workstation_request(prompt)


def test_snapshot_is_a_durable_child_without_model_or_http_handler_execution(monkeypatch):
    calls = []

    def hardware(self):
        calls.append(True)
        return copy.deepcopy(HARDWARE)

    monkeypatch.setattr(RunnerClient, "hardware", hardware)
    with session_factory()() as session:
        session.add(
            RuntimeInstance(
                runtime_key="llamacpp", name="External runtime", ownership="external", status="available"
            )
        )
        session.commit()
    with TestClient(app) as client:
        cid = setup_conversation()
        child_id = dispatch(client, cid)
        assert not calls
        reset_engine()  # queued operation survives API restart
        assert step() == child_id
        assert len(calls) == 1
        reset_engine()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert detail["active_run"] is None
        reply = detail["messages"][-1]
        assert reply["task_status"] == "succeeded"
        assert "GPU 7" in reply["content"] and "42%" in reply["content"]
        assert "unavailable" in reply["content"]
        assert "saved observations" in reply["content"]
        with session_factory()() as session:
            artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == child_id)))
            assert {row.artifact_type for row in artifacts} == {"markdown", "json"}
            observation = next(row for row in artifacts if row.artifact_type == "json")
            payload = (get_settings().data_dir / observation.relative_path).read_text()
            assert "/private/data" not in payload and "do not persist" not in payload
            assert json.loads(payload)["hardware"]["gpus"][0]["temperature_c"] is None
            events = list(session.scalars(select(RunEvent.event_type).where(RunEvent.run_id == child_id)))
            assert "tool.requested" in events and "tool.completed" in events
        assert step() is None
        assert len(calls) == 1


def test_cancel_during_snapshot_publishes_no_report(monkeypatch):
    def hardware(self):
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.executor_type == "station_snapshot"))
            request_cancel(session, run)
            session.commit()
        return copy.deepcopy(HARDWARE)

    monkeypatch.setattr(RunnerClient, "hardware", hardware)
    with TestClient(app) as client:
        cid = setup_conversation()
        child_id = dispatch(client, cid)
        step()
        with session_factory()() as session:
            assert session.get(Run, child_id).status == "canceled"
            assert not list(session.scalars(select(Artifact)))
        assert (
            client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["task_status"] == "canceled"
        )


@pytest.mark.parametrize("failure", ["permission", "runner"])
def test_failure_does_not_claim_success_or_publish_artifacts(monkeypatch, failure):
    calls = []

    def hardware(self):
        calls.append(True)
        raise RunnerUnavailable("runner offline")

    monkeypatch.setattr(RunnerClient, "hardware", hardware)
    with TestClient(app) as client:
        cid = setup_conversation()
        child_id = dispatch(client, cid, action="system.inspect")
        if failure == "permission":
            with session_factory()() as session:
                session.get(Run, child_id).effective_permissions = []
                session.commit()
        step()
        with session_factory()() as session:
            assert session.get(Run, child_id).status == "failed"
            assert not list(session.scalars(select(Artifact)))
        assert bool(calls) == (failure == "runner")
        assert client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["task_status"] == "failed"


def test_safe_claim_recovery_dispatches_one_observation(monkeypatch):
    monkeypatch.setattr(RunnerClient, "hardware", lambda self: copy.deepcopy(HARDWARE))

    def absent(self, run_id):
        raise RunnerError(404, "not a managed process")

    monkeypatch.setattr(RunnerClient, "inspect_process", absent)
    with TestClient(app) as client:
        cid = setup_conversation()
        child_id = dispatch(client, cid)
        with session_factory()() as session:
            child = session.get(Run, child_id)
            transition(session, child, RunStatus.CLAIMED, event_type="run.claimed")
            child.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
        step()
        assert step() is None
        with session_factory()() as session:
            assert session.get(Run, child_id).status == "succeeded"
            assert len(list(session.scalars(select(Artifact)))) == 2


def test_snapshot_does_not_accept_media_or_write_scope():
    with TestClient(app) as client:
        cid = setup_conversation()
        result = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Show GPU",
                "action": "system.inspect",
                "attachments": [{"name": "a.txt", "content": "ignored"}],
            },
        )
        assert result.status_code == 422
        with session_factory()() as session:
            assert not list(session.scalars(select(Run)))


def test_gpu_processes_are_reported_and_persisted_with_allowlisted_fields(monkeypatch):
    hardware = copy.deepcopy(HARDWARE)
    hardware["gpus"][0]["uuid"] = "GPU-test"
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: hardware)
    observation = {
        "status": "available",
        "sampled_at": "2026-10-14T08:00:00Z",
        "truncated": False,
        "unexpected_secret": "hidden",
        "processes": [
            {
                "gpu_uuid": "GPU-test",
                "pid": 4242,
                "name": "/private/python",
                "memory_used_mib": 512,
                "command_line": "--token secret",
            }
        ],
    }
    monkeypatch.setattr(RunnerClient, "gpu_processes", lambda _: observation)
    with TestClient(app) as client:
        cid = setup_conversation()
        rid = dispatch(client, cid)
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        message = detail["messages"][-1]
        assert "PID 4242" in message["content"] and "GPU 7" in message["content"]
        assert "python" in message["content"] and "512 MiB" in message["content"]
        assert "/private" not in message["content"] and "secret" not in message["content"]
        artifacts = client.get("/api/artifacts?run_id=" + rid).json()
        artifact = next(a for a in artifacts if a["type"] == "json")
        result = client.get("/api/artifacts/" + artifact["id"] + "/file").json()
        assert result["gpu_processes"]["processes"] == [
            {"gpu_uuid": "GPU-test", "pid": 4242, "name": "python", "memory_used_mib": 512}
        ]
        assert "secret" not in json.dumps(result)
        reset_engine()
        assert "PID 4242" in client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["content"]


def test_cancel_during_compute_query_does_not_publish_report(monkeypatch):
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: copy.deepcopy(HARDWARE))

    def query(self):
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.executor_type == "station_snapshot"))
            request_cancel(session, run)
            session.commit()
        return {"status": "available", "processes": []}

    monkeypatch.setattr(RunnerClient, "gpu_processes", query)
    with TestClient(app) as client:
        rid = dispatch(client, setup_conversation())
        step()
        assert client.get("/api/runs/" + rid).json()["status"] == "canceled"
        assert client.get("/api/artifacts?run_id=" + rid).json() == []


def test_live_process_api_unavailable_and_metadata_validation(monkeypatch):
    monkeypatch.setattr(
        RunnerClient,
        "gpu_processes",
        lambda _: {
            "status": "available",
            "processes": [
                {"gpu_uuid": "GPU-x", "pid": True, "name": "bad"},
                {
                    "gpu_uuid": "GPU-x",
                    "pid": 12,
                    "name": "/secret/bin/tool",
                    "memory_used_mib": float("nan"),
                    "secret": "hidden",
                },
            ],
        },
    )
    with TestClient(app) as client:
        result = client.get("/api/system/gpu-processes").json()
        assert result["status"] == "partial"
        assert result["processes"] == [
            {"gpu_uuid": "GPU-x", "pid": 12, "name": "tool", "memory_used_mib": None}
        ]

        def unavailable(self):
            raise RunnerUnavailable("private path")

        monkeypatch.setattr(RunnerClient, "gpu_processes", unavailable)
        result = client.get("/api/system/gpu-processes").json()
        assert result["status"] == "unavailable" and result["processes"] == []
