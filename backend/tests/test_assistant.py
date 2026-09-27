import io
import json

import pytest
from app.api import app
from app.assistant import AssistantExecutor
from app.db import reset_engine, session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, Run
from app.runs import request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


def create(client):
    result = client.post("/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def image(client):
    data = io.BytesIO()
    Image.new("RGB", (64, 64)).save(data, "PNG")
    return client.post(
        "/api/images/uploads", files={"file": ("reference.png", data.getvalue(), "image/png")}
    ).json()["id"]


def step():
    with session_factory()() as session:
        return tick(session, "assistant-test")


def test_two_references_dispatch_real_image_contract_and_project_results(monkeypatch):
    with TestClient(app) as client:
        cid = create(client)
        images = [image(client), image(client)]
        route = f"/api/chat/conversations/{cid}"
        result = client.post(
            route + "/messages", json={"content": "Zmień ubranie tej osobie", "image_artifact_ids": images}
        )
        assert result.status_code == 202, result.text
        planner = result.json()
        assert step() == planner["id"]
        detail = client.get(route).json()
        child = detail["active_run"]
        assert child["executor_type"] == "photo_pipe"
        assert child["parent_run_id"] == planner["id"]
        assert child["task_id"] == planner["task_id"]
        assert child["conversation_id"] == cid
        assert child["parameters"]["mode"] == "recompose"
        assert child["parameters"]["parent_artifact_ids"] == images
        assert detail["messages"][-1]["task_status"] == "queued"
        # Existing image executor's real runner contract is covered in test_images.
        with session_factory()() as session:
            run = session.get(Run, child["id"])
            transition(session, run, RunStatus.CLAIMED, event_type="run.claimed")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="run.started")
            session.add(
                Artifact(
                    artifact_type="image",
                    mime_type="image/png",
                    relative_path="artifacts/result.png",
                    run_id=run.id,
                    parent_artifact_ids=images,
                )
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        reset_engine()
        detail = client.get(route).json()
        assert detail["active_run"] is None
        assert detail["messages"][-1]["task_status"] == "succeeded"
        assert detail["messages"][-1]["artifacts"][0]["parent_artifact_ids"] == images
        assert step() is None  # Restart does not dispatch again.
        assert client.post(route + "/regenerate").status_code == 409


def test_agent_goal_image_does_not_dispatch_image_and_draft_is_disabled():
    with TestClient(app) as client:
        cid = create(client)
        client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Stwórz mi agenta który generuje obrazy co rano"},
        )
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        agent_id = detail["messages"][-1]["metadata"]["agent_id"]
        with session_factory()() as session:
            agent = session.get(Agent, agent_id)
            assert agent.enabled is False
            assert agent.cron_expr == "0 8 * * *"
            assert len(list(session.scalars(select(Run)))) == 1


def test_chat_fallback_has_one_task_and_does_not_feed_planner_annotation_to_model(monkeypatch):
    async def stream(self, **params):
        if params["max_tokens"] == 512:
            yield json.dumps({"action": "chat", "reason": "Answer the question"})
        else:
            assert params["messages"] == [{"role": "user", "content": "What is a GPU?"}]
            yield "A graphics processor."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        cid = create(client)
        route = f"/api/chat/conversations/{cid}"
        first = client.post(route + "/messages", json={"content": "What is a GPU?"}).json()
        step()
        child = client.get(route).json()["active_run"]
        assert child["executor_type"] == "chat"
        assert child["task_id"] == first["task_id"]
        step()
        detail = client.get(route).json()
        assert detail["active_run"] is None
        assert detail["messages"][-1]["content"] == "A graphics processor."


def test_cancel_during_planner_closes_stream_and_never_dispatches(monkeypatch):
    closed = []

    async def stream(self, **params):
        try:
            with session_factory()() as session:
                run = session.scalar(select(Run).where(Run.executor_type == "orchestrator"))
                request_cancel(session, run)
                session.commit()
            yield '{"action":"image.generate","reason":"Generate"}'
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        cid = create(client)
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Please make a picture"})
        step()
        with session_factory()() as session:
            runs = list(session.scalars(select(Run)))
            assert len(runs) == 1
            assert runs[0].status == "canceled"
        assert closed


def test_dispatch_transaction_rolls_back_child_on_failure(monkeypatch):
    from app import images

    original = images.create_image_run

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated interruption before commit")

    monkeypatch.setattr(images, "create_image_run", crash)
    with TestClient(app) as client:
        cid = create(client)
        client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "forest", "action": "image.generate"}
        )
        step()
        with session_factory()() as session:
            runs = list(session.scalars(select(Run)))
            assert len(runs) == 1
            assert runs[0].status == "failed"


@pytest.mark.parametrize(
    "output",
    ['{"action":"shell","reason":"run it"}', '{"action":"chat","reason":"ok","command":"bad"}', "not json"],
)
def test_invalid_planner_output_never_dispatches(monkeypatch, output):
    async def stream(self, **params):
        yield output

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        cid = create(client)
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Do something"})
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert len(detail["messages"][-1]["steps"]) == 1
        assert "Choose an action" in detail["messages"][-1]["content"]


def test_coding_cannot_gain_external_permission_from_model(monkeypatch):
    async def plan(*args):
        from app.assistant import Plan

        return Plan(action="coding.cursor", reason="Implement")

    monkeypatch.setattr(AssistantExecutor, "plan", plan)
    with TestClient(app) as client:
        cid = create(client)
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "add feature"})
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert "explicitly allow sharing" in detail["messages"][-1]["content"]
        assert len(detail["messages"][-1]["steps"]) == 1


def test_coding_scope_dispatch_and_stale_project_rejection():
    from app.models import Project

    with session_factory()() as session:
        project = Project(name="example", repo_path="/allowed/example", agent_rules="Keep tests passing")
        session.add(project)
        session.commit()
        scope = {
            "project_id": project.id,
            "expected_updated_at": project.updated_at.isoformat(),
            "files": ["app.py"],
            "external_ai": True,
        }
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Add feature", "action": "coding.cursor", "coding": scope},
        )
        assert response.status_code == 202
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = detail["active_run"]
        assert child["project_id"] == scope["project_id"]
        assert child["executor_type"] == "worktree_prepare"
        assert child["parameters"]["cursor"]["files"] == ["app.py"]
        assert child["parameters"]["cursor"]["guidance"] == "Keep tests passing"
        assert detail["messages"][-1]["steps"][-1]["location"] == "external"
        assert client.post(f"/api/runs/{child['id']}/cancel").status_code == 200
        assert (
            client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["task_status"] == "canceled"
        )
        scope["expected_updated_at"] = "2000-01-01T00:00:00Z"
        client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Add feature", "action": "coding.cursor", "coding": scope},
        )
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert detail["active_run"] is None
        assert "settings changed" in detail["messages"][-1]["content"]
