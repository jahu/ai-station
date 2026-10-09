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


@pytest.mark.parametrize("provider", ["cursor", "local", "explore"])
def test_coding_scope_dispatch_and_stale_project_rejection(provider):
    explore = provider == "explore"
    provider = "local" if explore else provider
    from app.models import Project

    with session_factory()() as session:
        project = Project(name="example", repo_path="/allowed/example", agent_rules="Keep tests passing")
        session.add(project)
        session.commit()
        scope = {
            "project_id": project.id,
            "expected_updated_at": project.updated_at.isoformat(),
            "files": ["app.py"],
            "external_ai": provider == "cursor",
        }
    if provider == "local":
        scope["max_repair_attempts"] = 2
    if explore:
        scope.update(files=[], explore=True)
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Add feature", "action": "coding." + provider, "coding": scope},
        )
        assert response.status_code == 202
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = detail["active_run"]
        assert child["project_id"] == scope["project_id"]
        assert child["executor_type"] == "worktree_prepare"
        if provider == "local":
            assert child["parameters"]["local_coding"]["max_repair_attempts"] == 2
        assert child["parameters"]["local_coding" if provider == "local" else "cursor"]["files"] == (
            [] if explore else ["app.py"]
        )
        assert (
            child["parameters"]["local_coding" if provider == "local" else "cursor"]["guidance"]
            == "Keep tests passing"
        )
        assert detail["messages"][-1]["steps"][-1]["location"] == (
            "local" if provider == "local" else "external"
        )
        assert ("external_ai" in response.json()["effective_permissions"]) == (provider == "cursor")
        assert client.post(f"/api/runs/{child['id']}/cancel").status_code == 200
        assert (
            client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["task_status"] == "canceled"
        )
        scope["expected_updated_at"] = "2000-01-01T00:00:00Z"
        client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Add feature", "action": "coding." + provider, "coding": scope},
        )
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert detail["active_run"] is None
        assert "settings changed" in detail["messages"][-1]["content"]


@pytest.mark.parametrize("action", ["auto", "coding.cursor", "coding.codex", "coding.local"])
def test_local_coding_scope_cannot_authorize_external_execution(action, monkeypatch):
    from app.models import Project

    async def unwanted_plan(*args):
        raise AssertionError("Explicit coding scope should not invoke a planner")

    monkeypatch.setattr(AssistantExecutor, "plan", unwanted_plan)
    with session_factory()() as session:
        project = Project(name="local", repo_path="/allowed/local")
        session.add(project)
        session.commit()
        scope = {
            "project_id": project.id,
            "expected_updated_at": project.updated_at.isoformat(),
            "files": ["README.md"],
        }
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Update documentation", "action": action, "coding": scope},
        )
        assert response.status_code == 202, response.text
        assert "external_ai" not in response.json()["effective_permissions"]
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = detail["active_run"]
        if action in {"coding.cursor", "coding.codex"}:
            assert child is None
            assert "explicitly allow sharing" in detail["messages"][-1]["content"]
        else:
            assert child["parameters"]["local_coding"]["model"] == response.json()["parameters"]["model"]
            assert "cursor" not in child["parameters"]
            assert child["metadata"]["next_executor"] == "local_proposal"


@pytest.mark.parametrize("action", ["coding.local", "coding.cursor", "coding.codex"])
def test_coding_rejects_media_instead_of_silently_ignoring_it(action):
    with TestClient(app) as client:
        cid = create(client)
        reference = image(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Change code", "action": action, "image_artifact_ids": [reference]},
        )
        assert response.status_code == 422
        assert "Remove media" in response.json()["detail"]
        assert client.get(f"/api/chat/conversations/{cid}").json()["active_run"] is None


@pytest.mark.parametrize("selected,action", [("cursor", "codex"), ("codex", "cursor"), ("codex", "codex")])
def test_external_coding_scope_binds_the_selected_provider(selected, action):
    from app.models import Project

    with session_factory()() as session:
        project = Project(name="fixture", repo_path="/allowed/fixture")
        session.add(project)
        session.commit()
        scope = {
            "project_id": project.id,
            "expected_updated_at": project.updated_at.isoformat(),
            "files": ["README.md"],
            "external_ai": True,
            "executor": selected,
        }
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Update documentation", "action": f"coding.{action}", "coding": scope},
        )
        assert response.status_code == 202, response.text
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        if selected == action:
            assert detail["active_run"]["metadata"]["next_executor"] == "codex_proposal"
            assert "codex" in detail["active_run"]["parameters"]
        else:
            assert detail["active_run"] is None
            assert "explicitly allow sharing" in detail["messages"][-1]["content"]


@pytest.mark.parametrize("provider", ["cursor", "codex"])
def test_assistant_external_coding_uses_native_cli_model(provider):
    from app.models import Project

    with session_factory()() as session:
        project = Project(name="native-model", repo_path="/allowed/native-model")
        session.add(project)
        session.commit()
        scope = {
            "project_id": project.id,
            "expected_updated_at": project.updated_at.isoformat(),
            "files": ["README.md"],
            "external_ai": True,
            "executor": provider,
            "model": "available-model",
        }
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Update documentation", "action": f"coding.{provider}", "coding": scope},
        )
        assert response.status_code == 202, response.text
        step()
        child = client.get(f"/api/chat/conversations/{cid}").json()["active_run"]
        assert child["parameters"][provider]["model"] == "available-model"
        assert child["metadata"]["next_executor"] == f"{provider}_proposal"
        rejected = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Update documentation",
                "action": f"coding.{provider}",
                "coding": {**scope, "model": "bad model!"},
            },
        )
        assert rejected.status_code == 422


def succeed(session, run):
    transition(session, run, RunStatus.CLAIMED, event_type="run.claimed")
    transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
    transition(session, run, RunStatus.RUNNING, event_type="run.started")
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")


def reviewed_proposal(conversation_id, *, publish=False):
    from app.models import Project
    from app.runs import create_run, create_task

    with session_factory()() as session:
        project = Project(
            name="reviewed",
            repo_path="/allowed/reviewed",
            pr_policy={
                "commit_task_branch": True,
                "push_task_branch": publish,
                "pr_to_integration": publish,
            },
        )
        session.add(project)
        session.flush()
        task = create_task(
            session,
            title="code",
            prompt="code",
            capability="assistant.orchestrate",
            conversation_id=conversation_id,
            project_id=project.id,
        )
        proposal = create_run(
            session,
            task,
            run_type="coding",
            capability="coding.local",
            executor_type="local_proposal",
            project_id=project.id,
            parameters={"worktree_run_id": "worktree-run", "commands": []},
            metadata={
                "coding_review": {
                    "branch": "ai/task-workspace",
                    "files": [{"path": "app.py", "diff": "+print(1)", "insertions": 1, "deletions": 0}],
                }
            },
        )
        succeed(session, proposal)
        session.commit()
        return project.id, proposal.id, project.updated_at.isoformat()


def test_conversation_projects_coding_review_for_inline_commit():
    from app.models import Message
    from app.runs import create_run

    with TestClient(app) as client:
        cid = create(client)
        _, proposal_id, _ = reviewed_proposal(cid)
        with session_factory()() as session:
            proposal = session.get(Run, proposal_id)
            plan = create_run(
                session,
                proposal.task,
                run_type="orchestration",
                capability="assistant.orchestrate",
                executor_type="orchestrator",
                execution_target="container",
            )
            succeed(session, plan)
            session.add(
                Message(
                    conversation_id=cid,
                    role="assistant",
                    content="Queued coding",
                    run_id=plan.id,
                    metadata_json={"orchestration": True},
                )
            )
            session.commit()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        review = next(row for row in detail["messages"][-1]["coding_runs"] if row["id"] == proposal_id)
        assert review["metadata"]["coding_review"]["files"][0]["path"] == "app.py"


def test_explicit_commit_reuses_domain_service_and_stays_on_source_task():
    with TestClient(app) as client:
        cid = create(client)
        _, proposal_id, _ = reviewed_proposal(cid)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Commit reviewed changes",
                "action": "coding.commit",
                "commit": {
                    "source_run_id": proposal_id,
                    "message": "Accept reviewed edits",
                    "reviewed": True,
                },
            },
        )
        assert response.status_code == 202, response.text
        assert "git_write" not in response.json()["effective_permissions"]
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = next(
            row for row in detail["messages"][-1]["coding_runs"] if row["executor_type"] == "reviewed_commit"
        )
        assert child["capability"] == "coding.commit"
        assert child["parent_run_id"] == proposal_id
        assert child["parameters"]["message"] == "Accept reviewed edits"
        assert child["effective_permissions"] == ["filesystem_read", "git_read", "git_write"]
        assert client.post(f"/api/runs/{child['id']}/cancel").status_code == 200
        assert (
            client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["task_status"] == "canceled"
        )


def test_model_cannot_grant_commit_or_publish(monkeypatch):
    async def plan(*args):
        from app.assistant import Plan

        return Plan(action="coding.commit", reason="Commit the work")

    monkeypatch.setattr(AssistantExecutor, "plan", plan)
    with TestClient(app) as client:
        cid = create(client)
        _, proposal_id, _ = reviewed_proposal(cid)
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "commit this"})
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert "cannot grant Git write permission" in detail["messages"][-1]["content"]
        assert not any(
            row["executor_type"] == "reviewed_commit" for row in detail["messages"][-1].get("coding_runs", [])
        )
        assert (
            client.post(
                f"/api/chat/conversations/{cid}/messages",
                json={
                    "content": "Commit",
                    "action": "coding.commit",
                    "commit": {"source_run_id": proposal_id},
                },
            ).status_code
            == 422
        )


def test_commit_rejects_another_conversation_and_unreviewed_body():
    with TestClient(app) as client:
        cid = create(client)
        other = create(client)
        _, proposal_id, _ = reviewed_proposal(other)
        assert (
            client.post(
                f"/api/chat/conversations/{cid}/messages",
                json={"content": "Commit", "action": "coding.commit"},
            ).status_code
            == 422
        )
        client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Commit",
                "action": "coding.commit",
                "commit": {
                    "source_run_id": proposal_id,
                    "message": "Steal this review",
                    "reviewed": True,
                },
            },
        )
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert "this conversation" in detail["messages"][-1]["content"]
        assert detail["active_run"] is None


def test_explicit_publish_reuses_approval_record_without_model_permission():
    from app.models import Approval
    from app.runs import create_run

    with TestClient(app) as client:
        cid = create(client)
        project_id, proposal_id, _ = reviewed_proposal(cid, publish=True)
        with session_factory()() as session:
            proposal = session.get(Run, proposal_id)
            commit = create_run(
                session,
                proposal.task,
                run_type="git",
                capability="coding.commit",
                executor_type="reviewed_commit",
                project_id=project_id,
                parent_run_id=proposal.id,
                parameters={"source_run_id": proposal.id, "worktree_run_id": "worktree-run"},
                metadata={
                    "git_commit": {
                        "commit": "a" * 40,
                        "branch": "ai/task-workspace",
                        "worktree_run_id": "worktree-run",
                    }
                },
            )
            succeed(session, commit)
            commit_id = commit.id
            session.commit()
        with session_factory()() as session:
            from app.models import Project

            version = session.get(Project, project_id).updated_at.isoformat()
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Publish reviewed changes",
                "action": "coding.publish",
                "publish": {
                    "source_run_id": commit_id,
                    "approved": True,
                    "repository": "owner/repo",
                    "commit": "a" * 40,
                    "base": "develop",
                    "expected_updated_at": version,
                    "title": "Reviewed task branch",
                    "body": "Validated locally.",
                },
            },
        )
        assert response.status_code == 202, response.text
        assert "network_external" not in response.json()["effective_permissions"]
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = next(
            row
            for row in detail["messages"][-1]["coding_runs"]
            if row["executor_type"] == "github_publication"
        )
        assert child["capability"] == "coding.publish"
        assert "network_external" in child["effective_permissions"]
        with session_factory()() as session:
            approval = session.scalar(select(Approval).where(Approval.run_id == child["id"]))
            assert approval.resolution == "granted"
            assert approval.action == "github.publish"
        assert client.post(f"/api/runs/{child['id']}/cancel").status_code == 200


def test_model_cannot_grant_github_publication(monkeypatch):
    async def plan(*args):
        from app.assistant import Plan

        return Plan(action="coding.publish", reason="Publish it")

    monkeypatch.setattr(AssistantExecutor, "plan", plan)
    with TestClient(app) as client:
        cid = create(client)
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "open a PR"})
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert "cannot grant publication permission" in detail["messages"][-1]["content"]
        assert not any(
            row["executor_type"] == "github_publication"
            for row in detail["messages"][-1].get("coding_runs", [])
        )


def test_explicit_runtime_load_uses_llama_service_without_model_permission():
    from app.models import ModelFile

    with session_factory()() as session:
        model = ModelFile(
            host_path="/models/assistant.gguf",
            filename="assistant.gguf",
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=1000,
            mtime=1,
        )
        session.add(model)
        session.commit()
        model_id = model.id
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Load the selected local GGUF",
                "action": "runtime.load",
                "load": {"model_file_id": model_id, "gpus": [2], "context_size": 4096},
            },
        )
        assert response.status_code == 202, response.text
        assert "manage_models" not in response.json()["effective_permissions"]
        assert "endpoint" not in response.json()["parameters"]
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = detail["active_run"]
        assert child["capability"] == "runtime.load"
        assert child["executor_type"] == "llama_load"
        assert child["parameters"]["gpus"] == [2]
        assert child["effective_permissions"] == ["manage_models", "filesystem_read"]
        assert detail["model"] == "llamacpp:" + model_id
        assert client.post(f"/api/runs/{child['id']}/cancel").status_code == 200


def test_explicit_runtime_stop_unloads_only_owned_instance():
    from app.models import RuntimeInstance

    with session_factory()() as session:
        instance = RuntimeInstance(
            runtime_key="llama.cpp",
            name="assistant.gguf",
            ownership="managed",
            status="ready",
            endpoint="llamacpp:owned",
        )
        session.add(instance)
        session.commit()
        instance_id = instance.id
    with TestClient(app) as client:
        cid = create(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Unload the selected owned llama.cpp instance",
                "action": "runtime.stop",
                "stop": {"instance_id": instance_id},
            },
        )
        assert response.status_code == 202, response.text
        assert "manage_models" not in response.json()["effective_permissions"]
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        child = detail["active_run"]
        assert child["capability"] == "runtime.stop"
        assert child["executor_type"] == "llama_stop"
        assert child["parameters"]["instance_id"] == instance_id
        assert child["effective_permissions"] == ["manage_models"]
        assert client.post(f"/api/runs/{child['id']}/cancel").status_code == 200


def test_model_cannot_grant_runtime_load_or_stop(monkeypatch):
    async def plan(*args):
        from app.assistant import Plan

        return Plan(action="runtime.load", reason="Load a model")

    monkeypatch.setattr(AssistantExecutor, "plan", plan)
    with TestClient(app) as client:
        cid = create(client)
        client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "load 27B"})
        step()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert "cannot load a model from a plan" in detail["messages"][-1]["content"]
        assert detail["active_run"] is None
        assert (
            client.post(
                f"/api/chat/conversations/{cid}/messages",
                json={"content": "Load", "action": "runtime.load"},
            ).status_code
            == 422
        )
