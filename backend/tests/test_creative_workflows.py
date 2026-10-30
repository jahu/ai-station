"""Full films/whole avatars and Task-wide lifecycle inside private workspaces."""

from uuid import uuid4

import pytest
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Run, Task
from app.runs import create_run
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_creative_sessions import create, send
from test_creative_sessions import generator as generator
from test_media_jobs import bridge as bridge


def work():
    with control_session_factory()() as queue:
        return tick(queue, "creative-workflow-fixture")


def test_full_film_uses_existing_plan_and_finishes_after_cpu_composition(accounts, bridge):
    _, alice, bob = accounts
    workspace = create(alice, "video")
    body = {
        "client_request_id": str(uuid4()),
        "request_kind": "job",
        "parameters": {
            "prompt": "A quiet landscape",
            "duration_seconds": 5,
            "width": 128,
            "height": 128,
            "steps": 4,
        },
    }
    response = alice.post("/api/creative/sessions/" + workspace["id"] + "/generate", json=body)
    assert response.status_code == 202, response.text
    turn = response.json()
    assert turn["request_kind"] == "job" and turn["job"]["total_segments"] == 2
    assert (
        alice.post("/api/creative/sessions/" + workspace["id"] + "/generate", json=body).json()["id"]
        == turn["id"]
    )
    assert work()
    partial = alice.get("/api/creative/sessions/" + workspace["id"]).json()["turns"][0]
    assert partial["status"] != "succeeded" and partial["job"]["completed_segments"] == 1
    for _ in range(3):
        work()
    complete = alice.get("/api/creative/sessions/" + workspace["id"]).json()["turns"][0]
    assert complete["status"] == "succeeded", complete
    assert len(complete["artifacts"]) == 1 and complete["artifacts"][0]["metadata"]["frames"] == 120
    assert complete["parameters"]["duration_seconds"] == 5
    assert bob.get("/api/artifacts/" + complete["artifacts"][0]["id"] + "/file").status_code == 404


@pytest.fixture
def whole_bridge(accounts, monkeypatch, tmp_path):
    from test_whole_avatar_jobs import bridge as native_fixture
    from test_whole_avatars import sources as source_fixture

    owner = accounts[1].get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as fixture:
        artifacts = source_fixture.__wrapped__(fixture, tmp_path)
        for artifact in artifacts:
            artifact.owner_id = owner
        fixture.commit()
        return native_fixture.__wrapped__(monkeypatch, fixture, artifacts)


@pytest.mark.parametrize("speech", [False, True])
def test_whole_recording_sonic_and_optional_speech_stay_one_creative_turn(accounts, whole_bridge, speech):
    from test_whole_avatars import PROFILE

    identifiers, native = whole_bridge
    _, alice, _ = accounts
    workspace = create(alice, "avatars")
    parameters = {
        "image_artifact_id": identifiers[0],
        "audio_artifact_id": identifiers[1],
        "generation_profile": PROFILE["recipe"]["id"],
    }
    if speech:
        parameters["speech_text"] = "Dzień dobry. To jest dokładny tekst do przeczytania."
    response = alice.post(
        "/api/creative/sessions/" + workspace["id"] + "/generate",
        json={"client_request_id": str(uuid4()), "request_kind": "job", "parameters": parameters},
    )
    assert response.status_code == 202, response.text
    for _ in range(5):
        work()
    history = alice.get("/api/creative/sessions/" + workspace["id"]).json()
    assert len(history["turns"]) == 1
    turn = history["turns"][0]
    assert turn["status"] == "succeeded", turn
    assert turn["parameters"]["generation_profile"] == PROFILE["recipe"]["id"]
    assert len(turn["artifacts"]) == 1 and turn["artifacts"][0]["type"] == "video"
    assert len(native["whole"]) == 1 and len(native["speech"]) == int(speech)
    if speech:
        assert native["speech"][0]["text"] == parameters["speech_text"]


def test_preparation_success_is_not_task_success_and_stop_is_owner_bound(accounts, generator):
    _, alice, bob = accounts
    workspace = create(alice)
    turn = send(alice, workspace["id"]).json()
    with control_session_factory()() as fixture:
        root = fixture.get(Run, turn["run_id"])
        root.status, root.finished_at = "succeeded", utcnow()
        child = create_run(
            fixture,
            fixture.get(Task, root.task_id),
            run_type="image",
            capability="image.generate",
            executor_type="fake",
            parent_run_id=root.id,
        )
        child.owner_id = root.owner_id
        fixture.commit()
        child_id = child.id
    history = alice.get("/api/creative/sessions/" + workspace["id"]).json()["turns"][0]
    assert history["run"]["status"] == "succeeded" and history["status"] == "queued"
    path = "/api/creative/sessions/" + workspace["id"] + "/turns/" + turn["id"] + "/cancel"
    assert bob.post(path).status_code == 404
    assert alice.post(path).json()["status"] == "canceled"
    with control_session_factory()() as fixture:
        assert fixture.get(Run, child_id).status == "canceled"
        assert fixture.get(Run, turn["run_id"]).status == "succeeded"


def test_full_job_variant_cannot_select_an_arbitrary_capability(accounts):
    _, alice, _ = accounts
    workspace = create(alice, "speech")
    response = alice.post(
        "/api/creative/sessions/" + workspace["id"] + "/generate",
        json={"client_request_id": str(uuid4()), "request_kind": "job", "parameters": {}},
    )
    assert response.status_code == 422
    assert alice.get("/api/creative/sessions/" + workspace["id"]).json()["turns"] == []


def test_administrator_inspects_selected_creative_history_without_impersonation(accounts, generator):
    admin, alice, bob = accounts
    workspace = create(alice)
    turn = send(alice, workspace["id"], "Alice private landscape").json()
    owner = alice.get("/api/auth").json()["user"]["id"]
    path = "/api/admin/users/" + owner + "/workspace/creative/" + workspace["id"]
    response = admin.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["turns"][0]["id"] == turn["id"]
    assert response.json()["turns"][0]["parameters"]["prompt"] == "Alice private landscape"
    assert bob.get(path).status_code == 403
    assert admin.get("/api/creative/sessions/" + workspace["id"]).status_code == 404
