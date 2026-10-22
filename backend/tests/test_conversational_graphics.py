import pytest
from app.api import app
from app.assistant import explicit_plan
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, Run
from app.paths import safe_join
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_chat_page_design import conversation, request
from test_images import png
from test_page_vision import drain
from test_page_vision import page_vision as page_vision
from test_vision import vision_runtime as vision_runtime


@pytest.mark.parametrize(
    "prompt,action",
    [
        ("Wygeneruj tę grafikę", "image.generate"),
        ("Stwórz plakat promujący kurs", "image.generate"),
        ("Generate a graphic promoting a course", "image.generate"),
        ("Create an illustration of a forest", "image.generate"),
        ("Stwórz prompt do grafiki promującej akademia.ai", "page.describe"),
        ("Create an image prompt for https://example.com/", "page.describe"),
        ("Generate a graphic design prompt for https://example.com/", "page.describe"),
        ('Create a poster labelled "image prompt"', "image.generate"),
        ("Generate a graphic of a forest, then animate it: mist moves", "image.generate_video"),
        ("Create an agent that generates graphics", "agent.create"),
        ("Create a project named Poster", "project.create"),
    ],
)
def test_graphics_wording_and_competing_action_priority(prompt, action):
    plan = explicit_plan(
        {"action": "auto", "content": prompt, "image_artifact_ids": [], "web_search": {"enabled": True}}
    )
    assert plan.action == action


def capture(api, route):
    queued = api.post(route + "/messages", json=request())
    assert queued.status_code == 202, queued.text
    drain()
    answer = api.get(route).json()["messages"][-1]
    assert answer["run_status"] == "succeeded", answer
    return answer["metadata"]["page_read"]


def send_graphic(api, route):
    queued = api.post(
        route + "/messages",
        json={"content": "Wygeneruj tę grafikę", "action": "auto", "web_search": {"enabled": True}},
    )
    assert queued.status_code == 202, queued.text
    return queued.json()


def test_website_visual_prompt_to_graphic_uses_saved_evidence_without_refetch(page_vision, monkeypatch):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        source = capture(api, route)
        brief_calls = []

        async def brief(self, **params):
            brief_calls.append(params)
            yield "Promotional artwork with the observed black background and bold white course title."

        monkeypatch.setattr(LocalChatProvider, "stream", brief)
        queued = send_graphic(api, route)
        with session_factory()() as session:
            assert tick(session, "graphic-dispatch") == queued["id"]
            assert tick(session, "graphic-brief") is not None
            photo = session.scalar(
                select(Run).where(Run.task_id == queued["task_id"], Run.executor_type == "photo_pipe")
            )
            assert photo and photo.status == "queued"
            assert photo.parameters["mode"] == "t2i" and photo.parameters["prompt_style"] == "prompt"
            assert (
                photo.parameters["prompt"]
                == "Promotional artwork with the observed black background and bold white course title."
            )
            assert photo.parameters["page_read_artifact_id"] == source["artifact_id"]
            assert not photo.parameters["inputs"]
            assert set(photo.effective_permissions) == {"filesystem_read", "workspace_write"}
            child = session.get(Run, photo.parameters["research_run_id"])
            assert (
                child.parameters["page_read"]["visual_analysis"]["artifact_id"]
                == source["visual_analysis"]["artifact_id"]
            )
        assert len(reports) == len(loads) == len(seen) == len(brief_calls) == 1
        context = brief_calls[0]["messages"][-1]["content"]
        assert "Visible JavaScript text" in context and "black background" in context


def test_changed_visual_observation_blocks_graphic_publication_without_refetch(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        source = capture(api, route)
        with session_factory()() as session:
            artifact = session.get(Artifact, source["visual_analysis"]["artifact_id"])
            safe_join(get_settings().data_dir, artifact.relative_path).write_text("changed observation")
        queued = send_graphic(api, route)
        with session_factory()() as session:
            assert tick(session, "graphic-dispatch")
            assert tick(session, "graphic-brief")
            assert not session.scalar(
                select(Run.id).where(Run.task_id == queued["task_id"], Run.executor_type == "photo_pipe")
            )
            brief = session.scalar(
                select(Run).where(Run.task_id == queued["task_id"], Run.executor_type == "chat")
            )
            assert brief.status == "failed"
        assert len(reports) == len(loads) == len(seen) == 1


def test_stop_prevents_graphic_but_preserves_prior_capture_and_vision(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        source = capture(api, route)
        queued = send_graphic(api, route)
        with session_factory()() as session:
            assert tick(session, "graphic-dispatch")
        response = api.post(route + "/tasks/" + queued["task_id"] + "/cancel")
        assert response.status_code == 200, response.text
        drain()
        with session_factory()() as session:
            assert not session.scalar(
                select(Run.id).where(Run.task_id == queued["task_id"], Run.executor_type == "photo_pipe")
            )
            assert session.get(Run, source["source_run_id"]).status == "succeeded"
            assert session.get(Run, source["visual_analysis"]["run_id"]).status == "succeeded"
        assert len(reports) == len(loads) == len(seen) == 1


def upload(api):
    response = api.post("/api/images/uploads", files={"file": ("reference.png", png(), "image/png")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_inspecting_selected_image_ignores_only_plain_web_availability(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        image = upload(api)
        response = api.post(
            route + "/messages",
            json={
                "content": "Describe this image",
                "image_artifact_ids": [image],
                "web_search": {"enabled": True},
            },
        )
        assert response.status_code == 202, response.text
        assert not response.json()["parameters"]["web_search"]["enabled"]
        drain()
        answer = api.get(route).json()["messages"][-1]
        assert answer["run_status"] == "succeeded" and answer["metadata"]["vision_model"] == "model.gguf"
        assert not reports and len(seen) == len(loads) == 1


def test_selected_edit_does_not_require_turning_web_off(page_vision, monkeypatch):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        image = upload(api)

        def no_provider(*args, **kwargs):
            raise AssertionError("A deterministic local edit must not require the Chat provider")

        monkeypatch.setattr("app.assistant.snapshot_provider", no_provider)
        monkeypatch.setattr("app.chat.snapshot_provider", no_provider)
        response = api.post(
            route + "/messages",
            json={
                "content": "Make the background blue",
                "action": "image.edit",
                "image_artifact_ids": [image],
                "web_search": {"enabled": True},
            },
        )
        assert response.status_code == 202, response.text
        assert not response.json()["parameters"]["web_search"]["enabled"]
        with session_factory()() as session:
            assert tick(session, "edit-dispatch")
            photo = session.scalar(
                select(Run).where(
                    Run.task_id == response.json()["task_id"], Run.executor_type == "photo_pipe"
                )
            )
            assert photo and photo.parameters["mode"] == "img2img"
            assert photo.parameters["parent_artifact_ids"] == [image]
            assert "network_read" not in photo.effective_permissions
        assert not reports and not seen and not loads


def test_inspection_with_an_exact_research_query_still_rejects_mixed_scope(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = conversation(api)
        image = upload(api)
        response = api.post(
            route + "/messages",
            json={
                "content": "Describe this image",
                "action": "image.describe",
                "image_artifact_ids": [image],
                "web_search": {"enabled": True, "query": "public topic"},
            },
        )
        assert response.status_code == 422, response.text
        with session_factory()() as session:
            assert not session.scalar(select(Run.id))
        assert not reports and not seen and not loads


@pytest.mark.parametrize("content", ["Upscale", "Powiększ tę grafikę"])
def test_explicit_image_input_and_plain_web_route_to_upscale(page_vision, content):
    with TestClient(app) as api:
        route = conversation(api)
        image = upload(api)
        response = api.post(
            route + "/messages",
            json={"content": content, "image_artifact_ids": [image], "web_search": {"enabled": True}},
        )
        assert response.status_code == 202, response.text
        assert not response.json()["parameters"]["web_search"]["enabled"]
        with session_factory()() as session:
            assert tick(session, "upscale-dispatch")
            photo = session.scalar(
                select(Run).where(
                    Run.task_id == response.json()["task_id"], Run.executor_type == "photo_pipe"
                )
            )
            assert photo and photo.parameters["mode"] == "upscale"
            assert photo.parameters["parent_artifact_ids"] == [image]


def test_selected_references_keep_recomposition_for_edits():
    plan = explicit_plan(
        {
            "action": "auto",
            "content": "Zmień tę grafikę: dodaj płaszcz",
            "image_artifact_ids": ["one", "two"],
            "web_search": {"enabled": True},
        }
    )
    assert plan.action == "image.recompose"
