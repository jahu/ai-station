import asyncio

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, Message, Run
from app.paths import safe_join
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_browser import fake_runner
from test_vision import vision_runtime as vision_runtime


def drain():
    with session_factory()() as session:
        for _ in range(20):
            if tick(session, "page-vision-test") is None:
                return
    raise AssertionError("Queue did not drain")


@pytest.fixture
def page_vision(vision_runtime, monkeypatch):
    reports, _ = fake_runner(monkeypatch)
    seen = []

    async def stream(self, **params):
        seen.append(params)
        if isinstance(params["messages"][0]["content"], list):
            yield "The screenshot shows a black background. This is a captured viewport, not the full site."
        else:
            yield "A sourced page answer."

    async def forbidden(*args, **kwargs):
        raise AssertionError("Saved captures must not issue search or HTTP requests")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr("app.web_search.search", forbidden)
    monkeypatch.setattr("app.http_fetch.fetch_public", forbidden)
    return seen, reports, vision_runtime[1]


def create(api):
    response = api.post(
        "/api/chat/conversations",
        json={
            "model": "unavailable-text-model",
            "execution_mode": "orchestrator",
        },
    )
    assert response.status_code == 201, response.text
    return "/api/chat/conversations/" + response.json()["id"]


def capture(api, route):
    response = api.post(
        route + "/messages",
        json={
            "content": "Read https://example.com/",
            "action": "chat",
            "web_search": {"enabled": True, "render_pages": True},
        },
    )
    assert response.status_code == 202, response.text
    drain()
    answer = api.get(route).json()["messages"][-1]
    assert answer["run_status"] == "succeeded", answer
    return answer


def inspect(api, route, image_id):
    response = api.post(
        route + "/messages",
        json={
            "content": "Analyze this page's visual design.",
            "action": "image.describe",
            "image_artifact_ids": [image_id],
            "web_search": {"enabled": False},
        },
    )
    assert response.status_code == 202, response.text
    drain()
    return api.get(route).json()["messages"][-1]


def test_saved_page_text_and_pixels_share_local_vision_and_artifact_provenance(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = create(api)
        original = capture(api, route)
        source = original["metadata"]["page_read"]
        image_id = source["pages"][0]["screenshot_artifact_id"]
        answer = inspect(api, route, image_id)
        assert answer["run_status"] == "succeeded", answer
        evidence = answer["metadata"]["page_read"]
        visual = evidence["visual_analysis"]
        assert evidence["origin_message_id"] == original["id"]
        assert evidence["selected_screenshot_id"] == image_id
        assert visual["location"] == "local" and visual["model"] == "model.gguf"
        assert "black background" in visual["description"]
        assert len(reports) == 1 and len(loads) == 1 and loads[0]["gpus"] == [7]
        parts = seen[-1]["messages"][0]["content"]
        assert "Visible JavaScript text" in parts[0]["text"] and "screenshot pixels" in parts[0]["text"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        with session_factory()() as session:
            run = session.get(Run, answer["run_id"])
            assert run.effective_permissions == ["filesystem_read"]
            assert "base64" not in str(run.parameters)
            artifact = session.get(Artifact, visual["artifact_id"])
            assert set(artifact.parent_artifact_ids) == {image_id, source["artifact_id"]}
            assert artifact.sha256 == visual["sha256"]


def test_only_the_selected_page_text_accompanies_its_frame(page_vision, monkeypatch):
    request = RunnerClient.request

    def distinct(self, method, path, payload=None):
        value = request(self, method, path, payload)
        if path.endswith("/report"):
            for index, page in enumerate(value["pages"]):
                page["text"] = f"ONLY PAGE {index} TEXT"
        return value

    monkeypatch.setattr(RunnerClient, "request", distinct)
    with TestClient(app) as api:
        route = create(api)
        response = api.post(
            route + "/messages",
            json={
                "content": "Read https://example.com/ and https://other.example.com/",
                "action": "chat",
                "web_search": {"enabled": True, "render_pages": True},
            },
        )
        assert response.status_code == 202, response.text
        drain()
        source = api.get(route).json()["messages"][-1]["metadata"]["page_read"]
        selected = source["pages"][1]["screenshot_artifact_id"]
        answer = inspect(api, route, selected)
        assert answer["run_status"] == "succeeded", answer
        parts = page_vision[0][-1]["messages"][0]["content"]
        assert "ONLY PAGE 1 TEXT" in parts[0]["text"] and "ONLY PAGE 0 TEXT" not in parts[0]["text"]
        assert answer["metadata"]["page_read"]["urls"] == ["https://other.example.com/"]


def test_multiple_followups_reuse_verified_visual_observations_without_new_tools(page_vision):
    seen, reports, loads = page_vision
    with TestClient(app) as api:
        route = create(api)
        original = capture(api, route)
        answer = inspect(api, route, original["metadata"]["page_read"]["pages"][0]["screenshot_artifact_id"])
        visual = answer["metadata"]["page_read"]["visual_analysis"]
        for prompt in [
            "Make it an Instagram prompt",
            "Use the same page for a poster",
            "Turn it into a banner",
        ]:
            response = api.post(
                route + "/messages",
                json={
                    "content": prompt,
                    "action": "chat",
                    "web_search": {"enabled": True},
                },
            )
            assert response.status_code == 202, response.text
            drain()
            followup = api.get(route).json()["messages"][-1]
            assert followup["run_status"] == "succeeded", followup
            assert (
                followup["metadata"]["page_read"]["visual_analysis"]["artifact_id"] == visual["artifact_id"]
            )
            assert "black background" in seen[-1]["messages"][-1]["content"]
            assert "Attribute visual findings" in seen[-1]["messages"][-1]["content"]
        assert len(reports) == len(loads) == 1


def test_repeated_plain_browser_followups_and_pre_origin_metadata_remain_compatible(page_vision):
    with TestClient(app) as api:
        route = create(api)
        original = capture(api, route)
        for _ in range(3):
            response = api.post(
                route + "/messages",
                json={
                    "content": "Make it an Instagram prompt",
                    "action": "chat",
                    "web_search": {"enabled": True},
                },
            )
            assert response.status_code == 202, response.text
            drain()
            answer = api.get(route).json()["messages"][-1]
            assert answer["run_status"] == "succeeded", answer
            assert (
                answer["metadata"]["page_read"]["artifact_id"]
                == original["metadata"]["page_read"]["artifact_id"]
            )
            with session_factory()() as session:
                # The deployed #346 reader did not save an origin key on reused messages.
                row = session.get(Message, answer["id"])
                page = dict(row.metadata_json["page_read"])
                page.pop("origin_message_id", None)
                row.metadata_json = {**row.metadata_json, "page_read": page}
                run = session.get(Run, answer["run_id"])
                scope = dict(run.parameters["page_read"])
                scope.pop("origin_message_id", None)
                # Older one-hop scopes point directly at the original successful answer.
                scope["source_message_id"] = original["id"]
                run.parameters = {**run.parameters, "page_read": scope}
                session.commit()
        assert len(page_vision[1]) == 1 and not page_vision[2]


def test_other_conversation_can_inspect_selected_pixels_without_inheriting_page_text(page_vision):
    with TestClient(app) as api:
        first = create(api)
        original = capture(api, first)
        second = create(api)
        answer = inspect(api, second, original["metadata"]["page_read"]["pages"][0]["screenshot_artifact_id"])
        assert answer["run_status"] == "succeeded", answer
        assert "page_read" not in answer["metadata"]
        assert "Visible JavaScript text" not in str(page_vision[0][-1]["messages"])


@pytest.mark.parametrize("target", ["page", "screenshot"])
def test_changed_capture_fails_before_loading_a_vision_model(page_vision, target):
    with TestClient(app) as api:
        route = create(api)
        original = capture(api, route)
        page = original["metadata"]["page_read"]
        image_id = page["pages"][0]["screenshot_artifact_id"]
        with session_factory()() as session:
            artifact = session.get(Artifact, page["artifact_id"] if target == "page" else image_id)
            safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed")
        inspect(api, route, image_id)
        assert not page_vision[2] and len(page_vision[0]) == 1


@pytest.mark.parametrize("target", ["file", "message", "image_binding", "model_binding", "missing_reference"])
def test_invalid_visual_evidence_fails_without_regeneration(page_vision, target):
    with TestClient(app) as api:
        route = create(api)
        original = capture(api, route)
        answer = inspect(api, route, original["metadata"]["page_read"]["pages"][0]["screenshot_artifact_id"])
        visual = answer["metadata"]["page_read"]["visual_analysis"]
        with session_factory()() as session:
            if target == "file":
                artifact = session.get(Artifact, visual["artifact_id"])
                safe_join(get_settings().data_dir, artifact.relative_path).write_text("Changed")
            elif target == "message":
                session.get(Message, answer["id"]).content = "Changed"
            elif target == "image_binding":
                run = session.get(Run, answer["run_id"])
                run.parameters = {**run.parameters, "vision_artifact_ids": ["unrelated"]}
            elif target == "model_binding":
                run = session.get(Run, answer["run_id"])
                run.parameters = {**run.parameters, "vision_model_name": "unrelated.gguf"}
            else:
                message = session.get(Message, answer["id"])
                page = dict(message.metadata_json["page_read"])
                page["visual_analysis"] = {"model": "model.gguf", "description": "Unbound"}
                message.metadata_json = {**message.metadata_json, "page_read": page}
            session.commit()
        before = len(page_vision[0])
        response = api.post(
            route + "/messages",
            json={
                "content": "Make it an Instagram prompt",
                "action": "chat",
                "web_search": {"enabled": True},
            },
        )
        assert response.status_code == 202, response.text
        drain()
        assert api.get(route).json()["messages"][-1]["run_status"] == "failed"
        assert len(page_vision[0]) == before and len(page_vision[1]) == len(page_vision[2]) == 1


def test_cancelled_pixel_inspection_does_not_publish_visual_analysis(page_vision, monkeypatch):
    from app.runs import request_cancel

    async def stream(self, **params):
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.capability == "chat.vision"))
            request_cancel(session, run)
            session.commit()
        await asyncio.sleep(0.3)
        yield "Never completed"

    with TestClient(app) as api:
        route = create(api)
        original = capture(api, route)
        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        answer = inspect(api, route, original["metadata"]["page_read"]["pages"][0]["screenshot_artifact_id"])
        assert answer["run_status"] == "canceled"
        assert "visual_analysis" not in answer["metadata"]["page_read"]
        assert api.get("/api/artifacts?run_id=" + answer["run_id"]).json() == []
