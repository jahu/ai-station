import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run, StudioRevision
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_studio_materials import board, material


def step():
    with session_factory()() as session:
        return tick(session, "studio-test")


@pytest.fixture
def local_model(monkeypatch):
    calls, responses = [], [json.dumps(board())]

    async def stream(self, **params):
        calls.append(params)
        yield responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls, responses


def request(**extra):
    return {"client_request_id": str(uuid4()), "expected_version": 1, "model": "fake-local", **extra}


def test_http_only_enqueues_and_worker_publishes_inspectable_storyboard(local_model):
    calls, _ = local_model
    with TestClient(app) as browser:
        created = material(browser)
        url = "/api/studio/materials/" + created["id"]
        body = request()
        queued = browser.post(url + "/plan", json=body)
        assert queued.status_code == 202, queued.text
        run = queued.json()
        assert run["executor_type"] == "studio_director" and run["status"] == "queued" and not calls
        assert browser.post(url + "/plan", json=body).json()["id"] == run["id"]
        assert browser.post(url + "/plan", json={**body, "feedback": "Different intent"}).status_code == 409
        assert step() == run["id"]
        done = browser.get("/api/runs/" + run["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        saved = browser.get(url + "/revisions").json()
        assert len(saved) == 1 and saved[0]["source_run_id"] == run["id"]
        assert saved[0]["storyboard"]["title"] == board()["title"]
        assert saved[0]["storyboard"]["scenes"][0]["visual_kind"] == "video"
        assert done["metadata"]["studio_revision_id"] == saved[0]["id"]
        assert done["parameters"]["director_schema_version"] == 1
        assert done["parameters"]["messages"][0]["role"] == "system"
        assert len(calls) == 1 and calls[0]["location"] == "local"
        assert calls[0]["json_output"] and calls[0]["require_complete"]
        activity = browser.get(url + "/activity").json()
        assert activity[0]["id"] == run["id"]
        artifacts = browser.get("/api/artifacts?run_id=" + run["id"]).json()
        assert artifacts and artifacts[0]["type"] == "json"
        assert step() is None


def test_invalid_plan_is_corrected_once_and_audio_policy_is_enforced(local_model):
    calls, responses = local_model
    responses[:] = [json.dumps(board("silent")), json.dumps(board())]
    with TestClient(app) as browser:
        created = material(browser)
        url = "/api/studio/materials/" + created["id"]
        run = browser.post(url + "/plan", json=request()).json()
        step()
        done = browser.get("/api/runs/" + run["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert len(calls) == 2
        assert len(done["parameters"]["messages"]) == 4
        assert "audio policy" in calls[1]["messages"][-1]["content"]


def test_failed_direction_keeps_previous_versions_and_publishes_no_fake_media(local_model):
    _, responses = local_model
    responses[:] = ["not valid json"]
    with TestClient(app) as browser:
        created = material(browser)
        url = "/api/studio/materials/" + created["id"]
        first = browser.post(
            url + "/revisions",
            json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": board()},
        ).json()
        run = browser.post(
            url + "/plan", json=request(expected_version=2, parent_revision_id=first["id"])
        ).json()
        step()
        done = browser.get("/api/runs/" + run["id"]).json()
        assert done["status"] == "failed" and done["error_type"] == "StudioPlanningFailed"
        assert browser.get(url + "/revisions").json() == [first]


def test_stop_during_stream_does_not_publish_a_partial_revision(local_model, monkeypatch):
    async def stream(self, **params):
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.executor_type == "studio_director"))
            from app.runs import request_cancel

            request_cancel(session, run)
            session.commit()
        yield json.dumps(board())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as browser:
        created = material(browser)
        url = "/api/studio/materials/" + created["id"]
        run = browser.post(url + "/plan", json=request()).json()
        step()
        assert browser.get("/api/runs/" + run["id"]).json()["status"] == "canceled"
        with session_factory()() as session:
            assert session.scalar(select(StudioRevision)) is None
        assert browser.get(url + "/revisions").json() == []
