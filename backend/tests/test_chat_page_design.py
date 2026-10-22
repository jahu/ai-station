import pytest
from app.api import app
from app.chat_page_design import requested_design_page
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run
from app.paths import safe_join
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_page_vision import drain
from test_page_vision import page_vision as page_vision
from test_vision import vision_runtime as vision_runtime


def request(content="Analyze https://example.com/ and give an image prompt", **extra):
    return {
        "content": content,
        "action": "chat",
        "web_search": {"enabled": True, "render_pages": True},
        **extra,
    }


@pytest.mark.parametrize(
    "content",
    [
        "Analyze https://example.com/ and give an image prompt",
        "przenalizuj stronę akademia.ai i daj mi prompt do stworzaenia grafiki promujacej ta strone",
        "What colors and layout does https://example.com/ use?",
    ],
)
def test_visual_intent_is_derived_from_the_explicit_current_request(content):
    assert requested_design_page(request(content))


@pytest.mark.parametrize(
    "change",
    [
        {"web_search": {"enabled": True}},
        {"web_search": {"enabled": False, "render_pages": True}},
        {"web_search": {"enabled": True, "render_pages": True, "query": "design"}},
        {"content": "Read https://example.com/ and summarize its offer"},
        {"content": "Read https://design.com/"},
        {"content": "Read https://example.com/design"},
        {"content": "Read colors.com text only"},
        {"content": "Read https://example.com/ design, text only"},
        {"content": "Przeczytaj https://example.com/ design, tylko treść"},
        {"content": "Read https://example.com/ and https://other.example.com/ for a design prompt"},
        {"content": 'Explain this example: "Analyze https://example.com/ and give an image prompt"'},
        {"content": "Explain: ```Analyze https://example.com/ and give an image prompt```"},
        {"content": "Describe colors on http://127.0.0.1/private"},
        {"action": "agent.create"},
        {"image_artifact_ids": ["image"]},
        {"attachments": [{"text": "Read https://example.com/ for design"}]},
        {"coding": {"project_id": "project"}},
    ],
)
def test_no_visual_or_browser_grant_from_unselected_scopes_or_quotes(change):
    assert requested_design_page(request(**change)) is None


def conversation(api):
    value = api.post(
        "/api/chat/conversations", json={"model": "unavailable-text-model", "execution_mode": "chat"}
    )
    assert value.status_code == 201, value.text
    return "/api/chat/conversations/" + value.json()["id"]


def test_one_send_composes_capture_local_pixels_and_repeated_followups(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(route + "/messages", json=request())
        assert queued.status_code == 202, queued.text
        assert not reports and not loads and not seen
        drain()
        answer = api.get(route).json()["messages"][-1]
        assert answer["run_status"] == "succeeded", answer
        evidence = answer["metadata"]["page_read"]
        assert evidence["visual_analysis"]["model"] == "model.gguf"
        assert len(seen) == len(reports) == len(loads) == 1
        parts = seen[0]["messages"][0]["content"]
        assert "Visible JavaScript text" in parts[0]["text"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        with session_factory()() as session:
            runs = list(session.scalars(select(Run).where(Run.task_id == queued.json()["task_id"])))
            assert len([r for r in runs if r.executor_type == "orchestrator"]) == 1
            assert len([r for r in runs if r.capability == "chat.vision"]) == 1
            assert not any(r.capability == "chat.completion" for r in runs)
            vision = session.get(Run, answer["run_id"])
            assert vision.effective_permissions == ["filesystem_read"]
            origin = session.get(Run, vision.parent_run_id)
            assert {"browser", "network_read", "filesystem_read", "manage_models"}.issubset(
                origin.effective_permissions
            )
        for prompt in ["Use the same page for a poster", "Make it an Instagram prompt"]:
            queued = api.post(
                route + "/messages",
                json={"content": prompt, "action": "chat", "web_search": {"enabled": True}},
            )
            assert queued.status_code == 202, queued.text
            drain()
            followup = api.get(route).json()["messages"][-1]
            assert followup["run_status"] == "succeeded", followup
            assert followup["metadata"]["page_read"]["visual_analysis"] == evidence["visual_analysis"]
        assert len(reports) == len(loads) == 1


def test_stop_before_capture_prevents_browser_and_model_load(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(route + "/messages", json=request())
        assert queued.status_code == 202, queued.text
        with session_factory()() as session:
            request_cancel(session, session.get(Run, queued.json()["id"]))
            session.commit()
        drain()
        assert not reports and not loads and not seen
        with session_factory()() as session:
            assert not session.scalar(select(Run.id).where(Run.capability == "chat.vision"))


def test_tampered_capture_never_loads_a_model(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(route + "/messages", json=request())
        assert queued.status_code == 202, queued.text
        with session_factory()() as session:
            assert tick(session, "capture-worker")
            image = session.scalar(select(Artifact).where(Artifact.artifact_type == "image"))
            assert image
            from app.config import get_settings

            safe_join(get_settings().data_dir, image.relative_path).write_bytes(b"changed capture")
        drain()
        assert len(reports) == 1 and not loads and not seen
        with session_factory()() as session:
            assert not session.scalar(select(Run.id).where(Run.capability == "chat.vision"))
        assert "changed" in api.get(route).json()["messages"][-1]["content"]


def test_missing_vision_pair_leaves_capture_but_no_partial_model_operations(page_vision):
    from app.models import ModelFile

    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(route + "/messages", json=request())
        assert queued.status_code == 202, queued.text
        with session_factory()() as session:
            for model in session.scalars(select(ModelFile)):
                model.availability = "missing"
            session.commit()
        drain()
        assert len(reports) == 1 and not loads and not seen
        detail = api.get(route).json()
        assert "mmproj" in detail["messages"][-1]["content"]
        with session_factory()() as session:
            root = session.get(Run, queued.json()["id"])
            assert root.parameters["image_artifact_ids"] == []
            assert not session.scalar(
                select(Run.id).where(Run.capability.in_(["chat.vision", "runtime.load"]))
            )


def test_stop_after_publication_cancels_the_task_without_vision_inference(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(route + "/messages", json=request())
        assert queued.status_code == 202, queued.text
        with session_factory()() as session:
            assert tick(session, "capture-worker")
            assert tick(session, "publication-worker")
            assert session.scalar(select(Run.id).where(Run.capability == "chat.vision"))
        stopped = api.post(route + "/tasks/" + queued.json()["task_id"] + "/cancel")
        assert stopped.status_code == 200, stopped.text
        drain()
        assert len(reports) == 1 and not loads and not seen
        with session_factory()() as session:
            vision = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            assert vision.status == "canceled"


def test_first_turn_replay_does_not_repeat_capture_or_model_preparation(page_vision):
    from uuid import uuid4

    from app.models import ChatTurnRequest

    seen, reports, loads = page_vision
    body = request(
        client_request_id=str(uuid4()),
        selection={"execution_mode": "chat", "model": "unavailable-text-model"},
    )
    with TestClient(app) as api:
        first = api.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        assert api.post("/api/chat/turns", json=body).json() == first.json()
        drain()
        again = api.post("/api/chat/turns", json=body)
        assert again.status_code == 202, again.text
        assert again.json()["conversation_id"] == first.json()["conversation_id"]
        drain()
        assert len(reports) == len(loads) == len(seen) == 1
        with session_factory()() as session:
            assert len(list(session.scalars(select(ChatTurnRequest)))) == 1
            assert len(list(session.scalars(select(Run).where(Run.executor_type == "browser")))) == 1


def test_attachments_cannot_silently_join_the_visual_page_scope(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(
            route + "/messages", json=request(attachments=[{"name": "note.txt", "content": "private data"}])
        )
        assert queued.status_code == 422, queued.text
        assert not reports and not seen and not loads
        with session_factory()() as session:
            assert not session.scalar(select(Run.id))


@pytest.mark.parametrize("change", ["grant", "capture", "marker"])
def test_followup_rejects_a_broken_orchestration_source_authority(page_vision, change):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        queued = api.post(route + "/messages", json=request())
        assert queued.status_code == 202, queued.text
        drain()
        assert api.get(route).json()["messages"][-1]["metadata"]["page_read"]["visual_analysis"]
        with session_factory()() as session:
            root = session.get(Run, queued.json()["id"])
            if change == "grant":
                root.effective_permissions = [p for p in root.effective_permissions if p != "browser"]
            elif change == "capture":
                root.parameters = {
                    **root.parameters,
                    "page_read": {**root.parameters["page_read"], "browser_run_id": "different-capture"},
                }
            else:
                root.parameters = {**root.parameters, "page_design": False}
            session.commit()
        followup = api.post(
            route + "/messages",
            json={
                "content": "Use the same page for a poster",
                "action": "chat",
                "web_search": {"enabled": True},
            },
        )
        assert followup.status_code == 202, followup.text
        drain()
        assert api.get(route).json()["messages"][-1]["run_status"] == "failed"
        assert len(seen) == len(reports) == len(loads) == 1
