from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.models import Conversation, Run, Task
from app.runs import create_run
from fastapi import HTTPException
from fastapi.testclient import TestClient


def test_stop_preparation_before_work_context_and_reject_late_children():
    with session_factory()() as s:
        chat = Conversation(model="plain", execution_mode="work")
        other = Conversation(model="plain")
        s.add_all([chat, other])
        s.flush()
        task = Task(title="New project", conversation_id=chat.id)
        s.add(task)
        s.flush()
        preparation = create_run(
            s, task, run_type="coding", executor_type="project_setup", capability="coding"
        )
        preparation.status = "running"
        cid, oid, tid, rid = chat.id, other.id, task.id, preparation.id
        s.commit()
    with TestClient(app) as c:
        route = f"/api/chat/conversations/{cid}/tasks/{tid}/cancel"
        assert c.post(f"/api/chat/conversations/{oid}/tasks/{tid}/cancel").status_code == 404
        assert c.post(f"/api/chat/conversations/{cid}/tasks/{uuid4()}/cancel").status_code == 404
        stopped = c.post(route)
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["run_ids"] == [rid]
        assert c.post(route).json()["run_ids"] == [rid]
    with session_factory()() as s:
        assert s.get(Run, rid).status == "cancel_requested"
        with pytest.raises(HTTPException, match="stopped"):
            create_run(
                s, s.get(Task, tid), run_type="coding", executor_type="worktree_prepare", capability="coding"
            )


def test_stale_stop_never_cancels_a_new_turn_in_the_same_conversation():
    with session_factory()() as s:
        chat = Conversation(model="plain")
        s.add(chat)
        s.flush()
        tasks = [Task(title=title, conversation_id=chat.id) for title in ("Old", "New")]
        s.add_all(tasks)
        s.flush()
        runs = [
            create_run(s, t, run_type="chat", executor_type="local_chat", capability="chat") for t in tasks
        ]
        runs[0].status = "succeeded"
        cid, old_task, new_run = chat.id, tasks[0].id, runs[1].id
        s.commit()
    with TestClient(app) as c:
        result = c.post(f"/api/chat/conversations/{cid}/tasks/{old_task}/cancel")
        assert result.status_code == 200 and result.json()["run_ids"] == []
        assert c.get("/api/runs/" + new_run).json()["status"] == "queued"
