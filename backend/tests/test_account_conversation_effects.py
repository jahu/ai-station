"""Conversation sound inherits private source, execution and editor ownership."""

from app.db import control_session_factory
from app.engine import tick
from app.models import Run
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_conversation_effects import mix_bridge as mix_bridge
from test_conversation_effects import sound_bridge as sound_bridge
from test_conversation_music import conversation
from test_effects import source_video


def test_conversation_mix_and_revision_are_private_and_other_accounts_cannot_select_source(
    accounts, mix_bridge
):
    _, alice, bob = accounts
    source = source_video(alice)
    cid = conversation(alice, "assistant")
    response = alice.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Rain", "action": "audio.effects", "effects": {"video_artifact_id": source}},
    )
    assert response.status_code == 202, response.text
    for _ in range(6):
        with control_session_factory()() as db:
            tick(db, "private-sound")
    message = alice.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
    assert message["task_status"] == "succeeded", message
    edit = message["sound_edits"][0]
    workspace = f"/api/creative/sessions/{edit['session_id']}"
    assert alice.get(workspace).status_code == 200
    turns = alice.get(workspace).json()["turns"]
    assert len(turns) == 1 and turns[0]["run_id"] == edit["run_id"]
    assert turns[0]["status"] == "succeeded"
    assert bob.get(workspace).status_code == 404
    assert bob.get(f"/api/timelines/{edit['session_id']}/revisions").status_code == 404
    assert bob.get(f"/api/runs/{edit['run_id']}").status_code == 404
    assert bob.get(f"/api/chat/conversations/{cid}").status_code == 404
    for artifact in message["artifacts"]:
        assert bob.get(f"/api/artifacts/{artifact['id']}/file").status_code == 404
    foreign = conversation(bob, "assistant")
    denied = bob.post(
        f"/api/chat/conversations/{foreign}/messages",
        json={"content": "Rain", "action": "audio.effects", "effects": {"video_artifact_id": source}},
    )
    assert denied.status_code == 422
    with control_session_factory()() as db:
        root = db.get(Run, response.json()["id"])
        assert root.owner_id
