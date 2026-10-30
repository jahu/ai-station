from uuid import uuid4

from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_creative_sessions import create
from test_effects import sound_bridge as sound_bridge
from test_effects import source_video, work


def test_effects_history_stem_preview_and_sources_are_private_and_submission_idempotent(
    accounts, sound_bridge
):
    _, alice, bob = accounts
    source = source_video(alice)
    workspace = create(alice, "effects")
    path = "/api/creative/sessions/" + workspace["id"]
    body = {
        "client_request_id": str(uuid4()),
        "parameters": {"video_artifact_id": source, "prompt": "Soft wind", "seed": 42},
    }
    first = alice.post(path + "/generate", json=body)
    assert first.status_code == 202, first.text
    assert alice.post(path + "/generate", json=body).json()["id"] == first.json()["id"]
    root = work()
    preview = work()
    turn = alice.get(path).json()["turns"][0]
    assert turn["status"] == "succeeded" and len(turn["artifacts"]) == 2
    assert len(sound_bridge["launches"]) == 2
    assert bob.get(path).status_code == 404
    assert bob.get("/api/artifacts/" + source + "/file").status_code == 404
    for rid in (root, preview):
        assert bob.get("/api/runs/" + rid).status_code == 404
    for artifact in turn["artifacts"]:
        assert bob.get("/api/artifacts/" + artifact["id"] + "/file").status_code == 404
    denied = bob.post("/api/audio/effects/runs", json=body["parameters"])
    assert denied.status_code == 422
