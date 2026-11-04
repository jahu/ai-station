from uuid import uuid4

from app.db import control_session_factory
from app.engine import tick
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_audio import audio_bridge as audio_bridge
from test_audio import reference
from test_creative_sessions import create


def test_private_speech_versions_retain_delivery_and_do_not_duplicate_generation(accounts, audio_bridge):
    _, alice, bob = accounts
    source = reference(alice)
    workspace = create(alice, "speech")
    path = "/api/creative/sessions/" + workspace["id"]
    parameters = {
        "text": "Dokładne słowa autora.",
        "reference_artifact_id": source["id"],
        "delivery": {"exaggeration": 1.1, "cfg_weight": 0.3, "temperature": 0.65},
    }
    body = {"client_request_id": str(uuid4()), "parameters": parameters}
    response = alice.post(path + "/generate", json=body)
    assert response.status_code == 202, response.text
    first = response.json()
    assert alice.post(path + "/generate", json=body).json()["id"] == first["id"]
    with control_session_factory()() as queue:
        tick(queue, "private-speech-delivery")
    saved = alice.get(path).json()["turns"][0]
    assert saved["status"] == "succeeded", saved
    assert saved["parameters"]["delivery"] == parameters["delivery"]
    assert saved["artifacts"][0]["metadata"]["speech_delivery"]["exaggeration"] == 1.1
    assert bob.get(path).status_code == 404
    assert bob.get("/api/artifacts/" + saved["artifacts"][0]["id"] + "/file").status_code == 404
    changed = {**parameters, "delivery": {**parameters["delivery"], "exaggeration": 0.3}}
    response = alice.post(
        path + "/generate",
        json={
            "client_request_id": str(uuid4()),
            "parameters": changed,
            "parent_turn_id": first["id"],
            "feedback": "Reduce expression; keep the words.",
        },
    )
    assert response.status_code == 202, response.text
    turns = alice.get(path).json()["turns"]
    assert [turn["parameters"]["delivery"]["exaggeration"] for turn in turns] == [1.1, 0.3]
