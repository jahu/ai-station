"""Selected document context composes with existing media preparation."""

import json

from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_documents import upload_document
from test_agent_media import create, drain, start
from test_agent_media import implemented_media as implemented_media
from test_music import music_bridge as music_bridge


def test_reviewed_document_supplies_goal_based_media_without_arbitrary_file_access(
    implemented_media, music_bridge, monkeypatch
):
    received = []

    async def describe(self, **kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        received.append(payload)
        assert payload["observations"][0]["tool"] == "read_documents"
        assert "Quiet piano for the library" in payload["observations"][0]["result"]["documents"][0]["text"]
        yield json.dumps({"description": "Quiet acoustic piano"})

    monkeypatch.setattr(LocalChatProvider, "stream", describe)
    api = TestClient(app)
    artifact = upload_document(api, b"Quiet piano for the library; no vocals.", "brief.md")
    agent = create(
        api,
        model="fake-local",
        tools=["read_documents", "create_media"],
        documents={"artifact_ids": [artifact["id"]]},
        media={
            "kind": "music",
            "description_source": "goal",
            "request": {"caption": "Follow the selected brief", "duration_seconds": 10},
        },
    )
    root = start(api, agent)
    with session_factory()() as s:
        drain(s)
        rows = list(s.scalars(select(Run).where(Run.task_id == root["task_id"])))
        assert all(r.status == "succeeded" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        output = next(r for r in rows if r.capability == "audio.music")
        assert output.parameters["caption"] == "Quiet acoustic piano"
    assert len(received) == 1
