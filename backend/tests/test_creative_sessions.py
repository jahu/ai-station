"""Persistent creative history, atomic enqueue and private-account access."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app import creative_sessions as creative
from app.data_access import DataAccessError, DataScope, ScopedSession
from app.db import control_session_factory, get_engine, migrate, reset_engine
from app.engine import tick
from app.models import CreativeTurn, Run, Task
from app.runs import create_run, create_task
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_images import bridge as bridge


@pytest.fixture
def generator(monkeypatch):
    calls = []

    class Request(BaseModel):
        model_config = ConfigDict(extra="forbid")
        prompt: str
        video_prompt: None = None

    def build(session, request):
        calls.append(request.prompt)
        task = create_task(
            session, title=request.prompt, prompt=request.prompt, capability="synthetic.generation"
        )
        return create_run(
            session,
            task,
            run_type="creative",
            capability="synthetic.generation",
            executor_type="fake",
            parameters={"prompt": request.prompt},
        )

    monkeypatch.setattr(creative, "builder", lambda _capability: (Request, build))
    return calls


def create(browser, capability="images"):
    response = browser.post(
        "/api/creative/sessions", json={"capability": capability, "title": "Mountain retreat"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def send(browser, identity, prompt="A quiet mountain retreat", **extra):
    return browser.post(
        "/api/creative/sessions/" + identity + "/generate",
        json={"client_request_id": str(uuid4()), "parameters": {"prompt": prompt}, **extra},
    )


@pytest.mark.parametrize("capability", ["images", "video", "music", "speech", "avatars"])
def test_generation_versions_survive_navigation_and_database_restart(accounts, generator, capability):
    _, alice, _ = accounts
    workspace = create(alice, capability)
    first = send(alice, workspace["id"])
    assert first.status_code == 202, first.text
    first = first.json()
    second = send(
        alice,
        workspace["id"],
        "The same retreat at sunset",
        parent_turn_id=first["id"],
        feedback="Make the lighting warmer",
    )
    assert second.status_code == 202, second.text
    assert second.json()["parent_turn_id"] == first["id"]
    with control_session_factory()() as queue:
        assert tick(queue, "creative-fixture-worker") == first["run_id"]
        assert tick(queue, "creative-fixture-worker") == second.json()["run_id"]
    reset_engine()
    migrate()
    history = alice.get("/api/creative/sessions/" + workspace["id"]).json()
    assert [row["position"] for row in history["turns"]] == [1, 2]
    assert all(row["run"]["status"] == "succeeded" for row in history["turns"])
    assert history["turns"][0]["parameters"]["prompt"] == "A quiet mountain retreat"
    assert history["turns"][1]["feedback"] == "Make the lighting warmer"
    assert alice.get("/api/creative/sessions?capability=" + capability).json()[0]["id"] == workspace["id"]
    older = alice.get("/api/creative/sessions/" + workspace["id"] + "?limit=1").json()
    assert older["next_before"] == 2 and older["turns"][0]["position"] == 2
    assert (
        alice.get("/api/creative/sessions/" + workspace["id"] + "?before=2&limit=1").json()["turns"][0]["id"]
        == first["id"]
    )


def test_drafts_versions_archival_and_foreign_references_are_private(accounts, generator):
    admin, alice, bob = accounts
    workspace = create(alice)
    path = "/api/creative/sessions/" + workspace["id"]
    saved = alice.patch(
        path, json={"expected_version": 1, "draft": {"prompt": "Still thinking", "width": 768}}
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert alice.patch(path, json={"expected_version": 1, "title": "Stale"}).status_code == 409
    assert bob.get(path).status_code == admin.get(path).status_code == 404
    assert admin.get(path, headers={"X-AI-Station-Inspect-All": "true"}).status_code == 200
    assert bob.patch(path, json={"expected_version": 2, "title": "Wrong owner"}).status_code == 404
    assert send(bob, workspace["id"]).status_code == 404
    foreign = send(bob, create(bob)["id"]).json()
    assert send(alice, workspace["id"], parent_turn_id=foreign["id"]).status_code == 404
    assert alice.patch(path, json={"expected_version": 2, "archived": True}).status_code == 200
    assert alice.get("/api/creative/sessions").json() == []
    assert alice.get("/api/creative/sessions?archived=true").json()[0]["draft"]["prompt"] == "Still thinking"
    assert send(alice, workspace["id"]).status_code == 409
    assert alice.patch(path, json={"expected_version": 3, "archived": False}).status_code == 200


def test_duplicate_send_is_one_atomic_generation_and_history_is_append_only(accounts, generator):
    _, alice, _ = accounts
    workspace = create(alice)
    receipt = str(uuid4())

    def submit(_):
        return send(alice, workspace["id"], client_request_id=receipt)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert all(row.status_code == 202 for row in responses), [row.text for row in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert generator == ["A quiet mountain retreat"]
    assert send(alice, workspace["id"], "Changed", client_request_id=receipt).status_code == 409
    owner = alice.get("/api/auth").json()["user"]["id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(owner)) as session:
        row = session.get(CreativeTurn, responses[0].json()["id"])
        row.feedback = "Rewritten past"
        with pytest.raises(DataAccessError, match="append-only"):
            session.flush()


def test_enqueue_failure_rolls_back_both_history_and_ordinary_task(accounts, generator, monkeypatch):
    _, alice, _ = accounts
    workspace = create(alice)
    request, build = creative.builder("images")

    def fail(session, body):
        build(session, body)
        raise HTTPException(409, "Synthetic unavailable profile")

    monkeypatch.setattr(creative, "builder", lambda _capability: (request, fail))
    assert send(alice, workspace["id"]).status_code == 409
    assert alice.get("/api/creative/sessions/" + workspace["id"]).json()["turns"] == []
    with control_session_factory()() as queue:
        assert queue.scalar(select(func.count()).select_from(Task)) == 0
        assert queue.scalar(select(func.count()).select_from(Run)) == 0


def test_receipt_collision_and_nonfinite_draft_fail_without_foreign_details(accounts, generator, monkeypatch):
    _, alice, bob = accounts
    workspace = create(alice)
    owner = bob.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as queue:
        task = Task(owner_id=owner, title="BOB PRIVATE TASK")
        queue.add(task)
        queue.commit()
        collision = task.id
    request_model, _ = creative.builder("images")

    def duplicate(session, body):
        session.add(Task(id=collision, title=body.prompt))
        session.flush()

    monkeypatch.setattr(creative, "builder", lambda _capability: (request_model, duplicate))
    response = send(alice, workspace["id"], client_request_id=collision)
    assert response.status_code == 409 and "BOB PRIVATE" not in response.text
    assert alice.get("/api/creative/sessions/" + workspace["id"]).json()["turns"] == []
    response = alice.patch(
        "/api/creative/sessions/" + workspace["id"],
        content='{"expected_version":1,"draft":{"scale":NaN}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_image_workspace_uses_real_image_builder_and_fake_native_pipeline(accounts, bridge):
    _, alice, bob = accounts
    workspace = create(alice)
    response = send(
        alice,
        workspace["id"],
        client_request_id=str(uuid4()),
        parameters={"mode": "t2i", "backend": "qwen", "prompt": "synthetic landscape", "gpu": "7"},
    )
    assert response.status_code == 202, response.text
    with control_session_factory()() as queue:
        tick(queue, "creative-image-fixture")
    history = alice.get("/api/creative/sessions/" + workspace["id"]).json()
    turn = history["turns"][0]
    assert turn["run"]["executor_type"] == "photo_pipe" and turn["run"]["status"] == "succeeded", turn["run"]
    assert len(turn["artifacts"]) == 1 and turn["artifacts"][0]["type"] == "image"
    artifact = turn["artifacts"][0]["id"]
    assert alice.get("/api/artifacts/" + artifact + "/file").status_code == 200
    assert bob.get("/api/artifacts/" + artifact + "/file").status_code == 404
