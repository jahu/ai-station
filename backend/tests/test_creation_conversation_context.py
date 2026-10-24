"""Creating a file from earlier ordinary conversation must not lose supplied data."""

import json

import pytest
from app.api import app
from app.db import session_factory
from app.models import Message
from fastapi.testclient import TestClient
from test_data_output_files import workbook
from test_local_file_creation import drain
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_creation_model_receives_the_prior_user_values_from_this_conversation(data_environment):
    data_environment.update(data_exports=1, exports={"result.xlsx": workbook()})
    with TestClient(app) as api:
        cid = api.post("/api/chat/conversations", json={"model": "unused", "execution_mode": "chat"}).json()[
            "id"
        ]
        with session_factory()() as db:
            db.add_all(
                [
                    Message(
                        conversation_id=cid,
                        role="user",
                        content="For our workbook use only the numbers 5, 8, 13 and label the column Fibonacci sample.",
                    ),
                    Message(
                        conversation_id=cid,
                        role="assistant",
                        content="Understood. I will use those three supplied values.",
                    ),
                ]
            )
            db.commit()
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={
                "content": "Create an Excel workbook using the numbers we discussed above",
                "data": {"operation": "create", "model": data_environment["model"]},
            },
        )
        assert response.status_code == 202, response.text
        rows = drain(response.json())
        assert all(row.status == "succeeded" for row in rows), [
            (row.executor_type, row.status, row.error_message) for row in rows
        ]
        generation = next(row for row in rows if row.executor_type == "agent_data_generate")
        request = json.loads(generation.parameters["messages"][1]["content"])
        context = json.dumps(request, ensure_ascii=False)
        assert "5, 8, 13" in context and "Fibonacci sample" in context
        assert request["inputs"] == [] and request["runtime"]["input_map"] == {}


def snapshot_fixture(db, *, content="Numbers: 5, 8, 13", metadata=None):
    from app.creation_context import freeze
    from app.models import Conversation

    conversation = Conversation(title="Only this conversation", model="unused")
    db.add(conversation)
    db.flush()
    source = Message(
        conversation_id=conversation.id, role="user", content=content, metadata_json=metadata or {}
    )
    db.add(source)
    db.flush()
    user = Message(
        conversation_id=conversation.id, role="user", content="Create an Excel workbook from our conversation"
    )
    db.add(user)
    db.flush()
    return conversation, source, user, freeze(db, conversation, user)


def test_snapshot_is_bounded_and_explicitly_marks_excerpts_and_older_context():
    from app.creation_context import MAX_CONTEXT, freeze, serialized

    with session_factory()() as db:
        conversation, source, user, value = snapshot_fixture(db, content="Numbers: " + "\x00" * 10000)
        assert len(serialized(value)) <= MAX_CONTEXT and value["messages"][0]["truncated"]
        for n in range(20):
            db.add(Message(conversation_id=conversation.id, role="user", content=f"Values {n}"))
        db.flush()
        latest = Message(conversation_id=conversation.id, role="user", content="Create a workbook")
        db.add(latest)
        db.flush()
        value = freeze(db, conversation, latest)
        assert len(value["messages"]) <= 8 and value["older_messages_omitted"]
        assert len(serialized(value)) <= MAX_CONTEXT


def test_snapshot_only_quotes_eligible_plain_messages_from_this_conversation():
    from app.creation_context import freeze
    from app.models import Conversation

    with session_factory()() as db:
        conversation, source, user, value = snapshot_fixture(db)
        other = Conversation(title="Private unrelated conversation", model="unused")
        db.add(other)
        db.flush()
        db.add_all(
            [
                Message(conversation_id=other.id, role="user", content="OTHER_PRIVATE_VALUE"),
                Message(conversation_id=conversation.id, role="system", content="SYSTEM_SECRET"),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="PARTIAL_REPLY",
                    metadata_json={"partial": True},
                ),
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="OLD_EDIT",
                    metadata_json={"superseded": True},
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="ROUTING_ONLY",
                    metadata_json={"routing_only": True},
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="Confirmed label: Approved numbers",
                    metadata_json={"orchestration": True},
                ),
            ]
        )
        db.flush()
        latest = Message(conversation_id=conversation.id, role="user", content="Create a CSV")
        db.add(latest)
        db.flush()
        value = freeze(db, conversation, latest)
        text = json.dumps(value)
        assert "Numbers: 5, 8, 13" in text and "Confirmed label: Approved numbers" in text
        assert all(
            marker not in text
            for marker in [
                "OTHER_PRIVATE_VALUE",
                "SYSTEM_SECRET",
                "PARTIAL_REPLY",
                "OLD_EDIT",
                "ROUTING_ONLY",
            ]
        )
        assert all(
            set(item) == {"message_id", "role", "content", "source_sha256", "truncated"}
            for item in value["messages"]
        )


@pytest.mark.parametrize("change", ["snapshot", "source", "ownership", "analysis", "duplicate"])
def test_context_rejects_changed_source_and_forged_authority(change):
    from copy import deepcopy
    from types import SimpleNamespace

    from app.creation_context import verify
    from app.models import Conversation

    with session_factory()() as db:
        conversation, source, user, value = snapshot_fixture(db)
        root = SimpleNamespace(
            conversation_id=conversation.id,
            parameters={"data": {"operation": "create"}, "data_creation_context": deepcopy(value)},
        )
        user.metadata_json = {"creation_context": deepcopy(value)}
        verify(db, root, user)
        if change == "snapshot":
            root.parameters["data_creation_context"]["messages"][0]["content"] = "Replaced numbers"
        elif change == "source":
            source.content = "New numbers"
        elif change == "ownership":
            other = Conversation(title="Other", model="unused")
            db.add(other)
            db.flush()
            source.conversation_id = other.id
        elif change == "analysis":
            root.parameters["data"]["operation"] = "analyze"
        else:
            root.parameters["data_creation_context"]["messages"] *= 2
            user.metadata_json = {"creation_context": deepcopy(root.parameters["data_creation_context"])}
        with pytest.raises(ValueError):
            verify(db, root, user)


def test_changed_context_prevents_native_workspace_and_inference(data_environment):
    from copy import deepcopy

    from app.models import Run

    with TestClient(app) as api:
        cid = api.post("/api/chat/conversations", json={"model": "unused", "execution_mode": "chat"}).json()[
            "id"
        ]
        with session_factory()() as db:
            db.add(Message(conversation_id=cid, role="user", content="Exact value: 83"))
            db.commit()
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={
                "content": "Create a CSV with the supplied value",
                "data": {"operation": "create", "model": data_environment["model"]},
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            params = deepcopy(root.parameters)
            params["data_creation_context"]["messages"][0]["content"] = "Altered value"
            root.parameters = params
            db.commit()
        rows = drain(response.json())
        assert any(row.status == "failed" for row in rows)
        assert data_environment["calls"] == 0 and not data_environment["jobs"]
