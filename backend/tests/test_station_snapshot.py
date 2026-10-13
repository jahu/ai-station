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
