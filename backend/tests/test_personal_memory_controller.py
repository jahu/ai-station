import pytest
from app.api import app
from app.engine import tick
from app.memory import upsert_memory
from app.models import Message, Run
from app.personal_memory import recalled, schedule_recall
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import model as model
from test_assistant_controller import tool
from test_personal_memory import consumer, execute


@pytest.mark.parametrize("direct", [False, True])
def test_controller_decision_and_visible_reply_keep_actual_memory_sources(session, model, direct):
    memory = upsert_memory(session, scope="global", content="The preferred editor is Helix.")
    memory_id = memory.id
    session.commit()
    model["outcomes"] = [{"kind": "text", "count": 1, "description": "Answer the question"}]
    model["reply"] = "The preferred editor is Helix."
    model["decisions"] = (
        [{"kind": "clarify", "reason": "Confirm the request", "response": "Do you mean Helix?"}]
        if direct
        else [tool("chat.reply", instruction="Answer the original question")]
    )
    api = TestClient(app)
    created = api.post("/api/chat/conversations", json={"model": "test-model", "execution_mode": "assistant"})
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    queued = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Which editor do I prefer?",
            "execution_mode": "assistant",
            "web_search": {"enabled": False},
        },
    )
    assert queued.status_code == 202, queued.text
    rid = queued.json()["id"]
    for _ in range(25):
        tick(session, "memory-controller-test")
        session.expire_all()
        root = session.get(Run, rid)
        if root.status in {"failed", "interrupted", "canceled", "succeeded"}:
            break
    assert root.status == "succeeded", root.error_message
    replies = list(
        session.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "assistant"))
    )
    visible = [
        row
        for row in replies
        if row.content
        and not row.metadata_json.get("routing_only")
        and not row.metadata_json.get("controller_internal")
    ]
    assert visible
    assert any(
        row.metadata_json.get("personal_memory", {}).get("sources", [{}])[0].get("id") == memory_id
        for row in visible
    )
    decision = session.get(Run, root.metadata_json["decision_run_id"])
    assert decision.parameters["decision_context"]["saved_user_context"]["sources"][0]["id"] == memory_id
    if not direct:
        chat = session.scalar(select(Run).where(Run.conversation_id == cid, Run.executor_type == "chat"))
        assert chat.parameters["personal_memory_recall_id"] == root.parameters["personal_memory_recall_id"]
        assert "Helix" in str(model["calls"][-1]["messages"])


def test_even_owned_recall_cannot_cross_conversation_boundaries(session):
    upsert_memory(session, scope="global", content="Personal context")
    first, conversation, _ = consumer(session)
    recall = schedule_recall(session, first, conversation, "context")
    execute(session, recall)
    other, _, _ = consumer(session)
    other.parameters = {**other.parameters, "personal_memory_recall_id": recall.id}
    assert recalled(session, other) is None
