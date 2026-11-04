from uuid import uuid4

import pytest
from app.db import control_session_factory
from app.models import Artifact, Run
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_audio import reference
from test_creative_sessions import create
from test_fish_speech import compressed_reference, work
from test_fish_speech import fish_bridge as fish_bridge


@pytest.mark.parametrize("phone", [False, True])
def test_private_creative_fish_history_and_transcripts_are_owner_bound(accounts, fish_bridge, phone):
    _, alice, bob = accounts
    source = compressed_reference(alice) if phone else reference(alice)
    workspace = create(alice, "speech")
    path = "/api/creative/sessions/" + workspace["id"]
    body = {
        "client_request_id": str(uuid4()),
        "parameters": {
            "text": "Moje dokładne słowa.",
            "reference_artifact_id": source["id"],
            "engine": "fish_s2_pro",
            "direction": "happy",
            "pace": "slow",
        },
    }
    first = alice.post(path + "/generate", json=body)
    assert first.status_code == 202, first.text
    assert alice.post(path + "/generate", json=body).json()["id"] == first.json()["id"]
    asr = work()
    speech = work()
    turn = alice.get(path).json()["turns"][0]
    assert turn["status"] == "succeeded", turn
    assert turn["parameters"]["engine"] == "fish_s2_pro"
    assert len(turn["artifacts"]) == 1
    assert turn["artifacts"][0]["metadata"]["direction"] == "happy"
    assert len(fish_bridge["starts"]) == 1
    assert bob.get(path).status_code == 404
    for rid in (asr, speech):
        assert bob.get("/api/runs/" + rid).status_code == 404
    with control_session_factory()() as db:
        transcript = db.get(Run, asr)
        aids = list(transcript.metadata_json["transcription"]["artifacts"].values())
    for aid in aids:
        assert bob.get("/api/artifacts/" + aid + "/file").status_code == 404
    assert bob.get("/api/artifacts/" + turn["artifacts"][0]["id"] + "/file").status_code == 404


@pytest.mark.parametrize("phone", [False, True])
def test_verified_reference_transcript_is_reused_and_later_tampering_stops_dispatch(
    accounts, fish_bridge, phone
):
    from app.config import get_settings

    _, alice, _ = accounts
    source = compressed_reference(alice) if phone else reference(alice)
    body = {"text": "Nowa wypowiedź.", "reference_artifact_id": source["id"], "engine": "fish_s2_pro"}
    first = alice.post("/api/audio/runs", json=body).json()
    asr = work()
    work()
    assert alice.get("/api/runs/" + first["id"]).json()["status"] == "succeeded"
    second = alice.post("/api/audio/runs", json=body).json()
    assert second["parameters"]["reference_text_provenance"]["kind"] == "cached_asr"
    assert second["parameters"]["reference_transcription_run_id"] == asr
    assert work() == second["id"]
    assert alice.get("/api/runs/" + second["id"]).json()["status"] == "succeeded"
    assert len(fish_bridge["reports"]) == 1
    third = alice.post("/api/audio/runs", json=body).json()
    with control_session_factory()() as db:
        transcript = db.get(Run, asr)
        artifact = db.get(Artifact, transcript.metadata_json["transcription"]["artifacts"]["txt"])
        path = get_settings().data_dir / artifact.relative_path
    path.write_text("Changed recorded words")
    work()
    assert alice.get("/api/runs/" + third["id"]).json()["status"] == "failed"
    assert len(fish_bridge["starts"]) == 2


def test_generated_voice_creative_history_and_files_remain_private_without_source_artifacts(
    accounts, fish_bridge
):
    _, alice, bob = accounts
    workspace = create(alice, "speech")
    path = "/api/creative/sessions/" + workspace["id"]
    body = {
        "client_request_id": str(uuid4()),
        "parameters": {
            "text": "Moje dokładne słowa.",
            "engine": "fish_s2_pro",
            "voice_source": "model",
            "reference_artifact_id": None,
            "direction": "whisper",
        },
    }
    first = alice.post(path + "/generate", json=body)
    assert first.status_code == 202, first.text
    assert alice.post(path + "/generate", json=body).json()["id"] == first.json()["id"]
    identity = work()
    turn = alice.get(path).json()["turns"][0]
    assert turn["status"] == "succeeded", turn
    assert (
        turn["parameters"]["voice_source"] == "model" and turn["parameters"]["reference_artifact_id"] is None
    )
    assert len(turn["artifacts"]) == 1 and turn["artifacts"][0]["parent_artifact_ids"] == []
    assert not fish_bridge["reports"]
    assert bob.get(path).status_code == 404 and bob.get("/api/runs/" + identity).status_code == 404
    assert bob.get("/api/artifacts/" + turn["artifacts"][0]["id"] + "/file").status_code == 404
