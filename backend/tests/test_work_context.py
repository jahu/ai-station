from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.models import Conversation, Message, Project, Run, Task, Worktree
from app.runs import create_run
from app.work_context import project_context
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def scope():
    with session_factory()() as s:
        conversation = Conversation(model="plain", execution_mode="work")
        project = Project(name="Example", repo_path="/configured/repo")
        s.add_all([conversation, project])
        s.flush()
        task = Task(
            title="Build project",
            project_id=project.id,
            conversation_id=conversation.id,
            capability="coding.local",
        )
        s.add(task)
        s.flush()
        worktree = Worktree(
            project_id=project.id,
            run_id=str(uuid4()),
            relative_path="worktrees/example",
            branch="ai/example",
            base_branch="develop",
            owned=True,
        )
        preparation = create_run(
            s, task, run_type="worktree", capability="coding.prepare", executor_type="worktree_prepare"
        )
        preparation.status = "succeeded"
        worktree.run_id = preparation.id
        s.add(worktree)
        s.flush()
        source = create_run(
            s,
            task,
            run_type="coding",
            capability="coding.local",
            executor_type="local_proposal",
            parameters={
                "worktree_id": worktree.id,
                "worktree_run_id": preparation.id,
                "model": "plain",
                "endpoint": "http://127.0.0.1:8080/v1",
                "prompt": "First instruction",
            },
            permissions=["filesystem_read", "workspace_write", "git_read", "network_read"],
        )
        source.status = "succeeded"
        s.commit()
        return {
            "conversation_id": conversation.id,
            "task_id": task.id,
            "source_id": source.id,
            "worktree_id": worktree.id,
        }


def body(scope, **updates):
    return {
        "client_request_id": str(uuid4()),
        "conversation_id": scope["conversation_id"],
        "expected_settings_version": 1,
        "execution_mode": "work",
        "content": "Add the next feature",
        "continuation": {"task_id": scope["task_id"], "expected_run_id": scope["source_id"]},
        **updates,
    }


def test_continuation_uses_same_task_workspace_and_receipt_without_routing(scope):
    with TestClient(app) as c:
        context = c.get("/api/chat/conversations/" + scope["conversation_id"]).json()["work_context"]
        assert context["ready"] and context["project_name"] == "Example"
        values = body(scope)
        response = c.post("/api/chat/turns", json=values)
        assert response.status_code == 202, response.text
        run = response.json()["run"]
        assert run["task_id"] == scope["task_id"] and run["executor_type"] == "local_proposal"
        assert (
            run["parameters"]["worktree_id"] == scope["worktree_id"]
            and run["parameters"]["user_prompt"] == "Add the next feature"
        )
        assert c.post("/api/chat/turns", json=values).json()["run"]["id"] == run["id"]
        assert c.post("/api/chat/turns", json=body(scope)).status_code == 409
        detail = c.get("/api/chat/conversations/" + scope["conversation_id"]).json()
        assert detail["active_run"]["id"] == run["id"] and detail["messages"][-1]["coding_runs"]
    with session_factory()() as s:
        assert len(list(s.scalars(select(Task)))) == 1
        assert len(list(s.scalars(select(Worktree)))) == 1
        assert s.get(Run, scope["source_id"]).metadata_json["review_status"] == "superseded"


@pytest.mark.parametrize(
    "updates",
    [
        {"execution_mode": "chat"},
        {"action": "chat"},
        {"web_search": {"enabled": True}},
        {"reasoning": {"enabled": True}},
        {"attachments": [{"name": "a.txt", "text": "private"}]},
    ],
)
def test_mixed_or_chat_scope_never_creates_work(scope, updates):
    with TestClient(app) as c:
        response = c.post("/api/chat/turns", json=body(scope, **updates))
        assert response.status_code == 422, response.text
    with session_factory()() as s:
        assert not list(s.scalars(select(Message)))
        assert len(list(s.scalars(select(Run)))) == 2


def test_cross_conversation_stale_source_and_external_disclosure(scope):
    with session_factory()() as s:
        other = Conversation(model="plain", execution_mode="work")
        s.add(other)
        s.commit()
        other_id = other.id
        source = s.get(Run, scope["source_id"])
        source.executor_type = "cursor_proposal"
        source.effective_permissions = ["filesystem_read", "workspace_write", "git_read", "external_ai"]
        s.commit()
    with TestClient(app) as c:
        assert c.post("/api/chat/turns", json=body(scope, conversation_id=other_id)).status_code == 422
        assert c.post("/api/chat/turns", json=body(scope)).status_code == 422
        request = body(scope)
        request["continuation"]["external_ai"] = True
        request["continuation"]["expected_run_id"] = str(uuid4())
        assert c.post("/api/chat/turns", json=request).status_code == 409
        request["continuation"]["expected_run_id"] = scope["source_id"]
        response = c.post("/api/chat/turns", json=request)
        assert response.status_code == 202, response.text
        assert response.json()["run"]["executor_type"] == "cursor_proposal"


def test_removed_or_uncertain_workspace_cannot_continue(scope):
    with session_factory()() as s:
        source = s.get(Run, scope["source_id"])
        source.status = "interrupted"
        s.commit()
        assert not project_context(s, scope["conversation_id"])["ready"]
    with TestClient(app) as c:
        assert c.post("/api/chat/turns", json=body(scope)).status_code == 409


def test_task_stop_cancels_all_stages_blocks_late_publication_and_can_be_continued(scope):
    from app.coding_tasks import queue_validation
    from app.models import Task

    with TestClient(app) as client:
        request = body(scope)
        first = client.post("/api/chat/turns", json=request).json()["run"]
        with session_factory()() as session:
            task = session.get(Task, scope["task_id"])
            validation = create_run(
                session,
                task,
                run_type="validation",
                capability="coding.validate",
                executor_type="project_validation",
                parameters={"commands": []},
            )
            validation_id = validation.id
            session.commit()
        stopped = client.post("/api/coding/sessions/" + scope["task_id"] + "/cancel")
        assert stopped.status_code == 200, stopped.text
        assert set(stopped.json()["run_ids"]) == {first["id"], validation_id}
        assert client.get("/api/runs/" + first["id"]).json()["status"] == "canceled"
        assert client.get("/api/runs/" + validation_id).json()["status"] == "canceled"
        with session_factory()() as session:
            previous = session.get(Run, scope["source_id"])
            previous.parameters = {**previous.parameters, "commands": [{"argv": ["pytest"], "kind": "test"}]}
            queue_validation(session, previous)
            session.commit()
            assert previous.metadata_json["validation_status"] == "canceled"
        again = body(scope)
        again["continuation"]["expected_run_id"] = first["id"]
        response = client.post("/api/chat/turns", json=again)
        assert response.status_code == 202, response.text
        assert response.json()["run"]["status"] == "queued"


def test_stop_serializes_with_in_flight_child_publication(scope):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.task_control import cancel_task, lock_task
    from fastapi import HTTPException

    published, release, stopping = Event(), Event(), Event()

    def publisher():
        with session_factory()() as session:
            task = session.get(Task, scope["task_id"])
            lock_task(session, task)
            child = create_run(
                session,
                task,
                run_type="validation",
                capability="coding.validate",
                executor_type="project_validation",
            )
            child_id = child.id
            published.set()
            assert release.wait(5)
            session.commit()
            return child_id

    def stop():
        assert published.wait(5)
        with session_factory()() as session:
            stopping.set()
            task = session.get(Task, scope["task_id"])
            result = cancel_task(session, task)
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        creating = pool.submit(publisher)
        canceling = pool.submit(stop)
        assert stopping.wait(5)
        release.set()
        child_id = creating.result(timeout=10)
        result = canceling.result(timeout=10)
    assert child_id in result["run_ids"]
    with session_factory()() as session:
        assert session.get(Run, child_id).status == "canceled"
        with pytest.raises(HTTPException, match="409"):
            create_run(
                session,
                session.get(Task, scope["task_id"]),
                run_type="coding",
                capability="coding.local",
                executor_type="local_proposal",
            )
