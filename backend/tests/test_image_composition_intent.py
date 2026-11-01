"""Reference composition dispatches PhotoPipe and waits for busy owned GPUs."""

import pytest
from app.api import app
from app.db import session_factory
from app.image_composition_intent import requested
from app.llama import instances
from app.models import Run
from app.runner_client import RunnerClient
from app.runs import create_run, create_task, transition
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant import image, step
from test_conversation_media import conversation
from test_llama import load, tick_once
from test_llama import managed as managed  # noqa: F401

EXACT = (
    "Umieść osobę z drugiego zdjęcia w scenie z pierwszego zdjęcia, obok czerwonego roweru. "
    "Zachowaj tożsamość dorosłej ubranej kobiety, jej granatowy sweter i naturalne światło. "
    "Wygeneruj jedno nowe zdjęcie."
)


@pytest.mark.parametrize(
    "prompt",
    [
        EXACT,
        "Put the person from the second photo into the scene from the first photo.",
        "Combine these images into one photograph.",
    ],
)
@pytest.mark.parametrize("web", [False, True])
def test_ordered_photo_composition_waits_without_stopping_active_model(managed, prompt, web, monkeypatch):
    model_id, _ = managed
    capability_requests = []

    def request(_, method, path, body=None):
        assert (method, path, body) == ("GET", "/v1/photo/capabilities", None)
        capability_requests.append(path)
        return {"configuration_source": "external"}

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        load(client, model_id)
        tick_once()
        with session_factory()() as session:
            instance = instances(session)[0]
            task = create_task(
                session, title="Independent active chat", prompt="Hello", capability="chat.completion"
            )
            busy = create_run(
                session,
                task,
                run_type="chat",
                capability="chat.completion",
                executor_type="chat",
                parameters={"model": "llamacpp:" + model_id, "endpoint": instance.endpoint},
            )
            for status in ["claimed", "preparing", "running"]:
                transition(session, busy, status, event_type="test." + status)
            busy_id = busy.id
            session.commit()
        cid = conversation(client, "assistant")
        ids = [image(client), image(client)]
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": prompt,
                "image_artifact_ids": ids,
                "web_search": {"enabled": web},
                "media_translation": {"mode": "off"},
            },
        )
        assert response.status_code == 202, response.text
        assert step() == response.json()["id"]
        with session_factory()() as session:
            children = list(session.scalars(select(Run).where(Run.parent_run_id == response.json()["id"])))
            assert len(children) == 1
            photo = children[0]
            photo_id, task_id = photo.id, photo.task_id
            assert photo.executor_type == "photo_pipe" and photo.parameters["mode"] == "recompose"
            assert photo.parameters["parent_artifact_ids"] == ids
        assert step() == photo_id  # Actual executor must defer instead of launching on the busy GPUs.
        assert capability_requests == ["/v1/photo/capabilities"]
        with session_factory()() as session:
            photo = session.get(Run, photo_id)
            assert photo.status == "queued" and photo.metadata_json["resource_wait"]["reason"] == "gpu"
            assert not photo.metadata_json.get("dispatch_attempted")
            assert session.get(Run, busy_id).status == "running"
            assert instances(session)[0].status == "ready"
            assert not list(session.scalars(select(Run).where(Run.executor_type == "llama_stop")))
            assert len(list(session.scalars(select(Run).where(Run.executor_type == "llama_load")))) == 1
        canceled = client.post(f"/api/chat/conversations/{cid}/tasks/{task_id}/cancel")
        assert canceled.status_code == 200
        assert client.get("/api/runs/" + photo_id).json()["status"] == "canceled"
        assert client.get("/api/runs/" + busy_id).json()["status"] == "running"


@pytest.mark.parametrize(
    "prompt",
    [
        "Explain how to put a person in the scene from a photograph",
        "Do not put the person in this scene",
        "Wstaw komentarz do kodu przetwarzającego obrazy",
        "Połącz moduły Pythona odczytujące zdjęcia",
        "> Umieść osobę w scenie z pierwszego zdjęcia",
        'Explain: "Put the person into the scene from this photo"',
        "```text\nCombine these images\n```",
    ],
)
def test_discussion_quotes_and_code_are_not_composition_instructions(prompt):
    assert not requested(prompt)
