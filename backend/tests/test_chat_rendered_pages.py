import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, Run
from app.paths import safe_join
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_browser import fake_runner
from test_chat_pages import conversation, step
from test_chat_turns import turn


@pytest.fixture
def rendered(monkeypatch):
    reports, canceled = fake_runner(monkeypatch)
    seen = []

    async def stream(self, **params):
        seen.append(params)
        yield "A sourced answer about [this page](https://example.com/)."

    async def forbidden(*args, **kwargs):
        raise AssertionError("Rendering must not substitute snippets or static HTTP text")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(LocalChatProvider, "models", lambda self: ["test-model", "fixture-model"])
    monkeypatch.setattr("app.http_fetch.fetch_public", forbidden)
    monkeypatch.setattr("app.web_search.search", forbidden)
    return seen, reports, canceled


def send(api, route, **updates):
    response = api.post(
        route + "/messages",
        json={
            "content": "Read https://example.com/",
            "web_search": {"enabled": True, "render_pages": True},
            **updates,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


@pytest.mark.parametrize("content", ["Read https://example.com/", "https://example.com/"])
def test_rendering_is_an_owned_prerequisite_and_keeps_audited_sources(rendered, content):
    seen, reports, _ = rendered
    with TestClient(app) as api:
        route = conversation(api)
        queued = send(api, route, content=content)
        browser_id = queued["parameters"]["page_read"]["browser_run_id"]
        child = api.get("/api/runs/" + browser_id).json()
        assert child["status"] == "queued" and not reports
        assert child["parent_run_id"] == queued["id"] and child["task_id"] == queued["task_id"]
        assert child["conversation_id"] == queued["conversation_id"]
        assert set(queued["effective_permissions"]) == {"browser", "network_read"}
        step()
        answer = api.get(route).json()["messages"][-1]
        assert answer["run_status"] == "succeeded", answer
        source = answer["metadata"]["page_read"]
        assert source["renderer"] == "browser" and source["source_run_id"] == browser_id
        assert source["pages"][0]["text"] == "Visible JavaScript text"
        assert "requests" not in source["pages"][0]
        assert "Visible JavaScript text" in seen[0]["messages"][-1]["content"]
        assert "not pixels" in seen[0]["messages"][-1]["content"]
        artifacts = api.get("/api/artifacts?run_id=" + browser_id).json()
        assert {row["type"] for row in artifacts} == {"image", "json"}
        assert source["artifact_id"] in {row["id"] for row in artifacts}


def test_rendered_followup_reuses_original_capture_without_browser_availability(rendered, monkeypatch):
    seen, reports, _ = rendered
    with TestClient(app) as api:
        route = conversation(api)
        send(api, route)
        step()
        original = api.get(route).json()["messages"][-1]["metadata"]["page_read"]
        monkeypatch.setattr("app.browser.available", lambda: {"available": False})
        send(api, route, content="Make it an Instagram prompt", web_search={"enabled": True})
        step()
        answer = api.get(route).json()["messages"][-1]
        assert answer["run_status"] == "succeeded", answer
        saved = answer["metadata"]["page_read"]
        assert saved["artifact_id"] == original["artifact_id"]
        assert saved["captured_at"] == original["captured_at"] and saved["reused_from_message_id"]
        assert len(reports) == 1 and len(seen) == 2


def test_stop_cancels_only_the_owned_browser_before_dispatch(rendered):
    with TestClient(app) as api:
        route = conversation(api)
        queued = send(api, route)
        browser_id = queued["parameters"]["page_read"]["browser_run_id"]
        unrelated = api.post("/api/browser/runs", json={"urls": ["https://example.org/"]}).json()
        response = api.post("/api/runs/" + queued["id"] + "/cancel")
        assert response.status_code == 200
        assert api.get("/api/runs/" + browser_id).json()["status"] == "canceled"
        assert api.get("/api/runs/" + unrelated["id"]).json()["status"] == "queued"
        assert rendered[0] == [] and rendered[1] == {}


def test_stop_during_render_prevents_inference_and_cleans_the_child(rendered, monkeypatch):
    _, _, canceled = rendered
    request = RunnerClient.request
    with TestClient(app) as api:
        route = conversation(api)
        queued = send(api, route)

        def stop(self, method, path, payload=None):
            if path == "/v1/runs/browser":
                assert api.post("/api/runs/" + queued["id"] + "/cancel").status_code == 200
            return request(self, method, path, payload)

        monkeypatch.setattr(RunnerClient, "request", stop)
        step()
        assert api.get("/api/runs/" + queued["id"]).json()["status"] == "canceled"
        assert queued["parameters"]["page_read"]["browser_run_id"] in canceled
        assert not rendered[0]


@pytest.mark.parametrize("mode", ["failed", "uncertain", "permission"])
def test_unsuccessful_browser_never_runs_the_model(rendered, monkeypatch, mode):
    fake_runner(monkeypatch, exit_code=1 if mode == "failed" else 0, uncertain=mode == "uncertain")
    with TestClient(app) as api:
        route = conversation(api)
        queued = send(api, route)
        if mode == "permission":
            with session_factory()() as session:
                child = session.get(Run, queued["parameters"]["page_read"]["browser_run_id"])
                child.effective_permissions = ["network_read"]
                session.commit()
        step()
        result = api.get("/api/runs/" + queued["id"]).json()
        assert result["status"] == "failed" and result["error_type"] == "PrerequisiteFailed", result
        assert not rendered[0]


@pytest.mark.parametrize("alteration", ["artifact", "screenshot", "ownership", "parent_permission"])
def test_changed_evidence_or_ownership_is_rejected_before_inference(rendered, alteration):
    with TestClient(app) as api:
        route = conversation(api)
        queued = send(api, route)
        with session_factory()() as session:
            tick(session, "render-only")
            child = session.get(Run, queued["parameters"]["page_read"]["browser_run_id"])
            assert child.status == "succeeded"
            if alteration == "artifact":
                artifact = session.get(Artifact, child.metadata_json["browser"]["artifact_id"])
                safe_join(get_settings().data_dir, artifact.relative_path).write_text("{}")
            elif alteration == "screenshot":
                image_id = child.metadata_json["browser"]["pages"][0]["screenshot_artifact_id"]
                artifact = session.get(Artifact, image_id)
                safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed")
            elif alteration == "ownership":
                child.parent_run_id = None
            else:
                session.get(Run, queued["id"]).effective_permissions = ["network_read"]
            session.commit()
        step()
        assert api.get("/api/runs/" + queued["id"]).json()["status"] == "failed"
        assert not rendered[0]


def test_unavailable_browser_rolls_back_the_turn_without_a_partial_graph(monkeypatch):
    monkeypatch.setattr("app.browser.available", lambda: {"available": False})
    with TestClient(app) as api:
        route = conversation(api)
        response = api.post(
            route + "/messages",
            json={
                "content": "Read https://example.com/",
                "web_search": {"enabled": True, "render_pages": True},
            },
        )
        assert response.status_code == 503 and "JavaScript" in response.text
        with session_factory()() as session:
            assert not list(session.scalars(select(Run)))


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": False, "render_pages": True},
        {"enabled": True, "query": "an exact search", "render_pages": True},
    ],
)
def test_render_permission_cannot_be_hidden_in_an_offline_or_custom_search(rendered, options):
    with TestClient(app) as api:
        route = conversation(api)
        response = api.post(
            route + "/messages", json={"content": "Read https://example.com/", "web_search": options}
        )
        assert response.status_code == 422 and not rendered[1]


@pytest.mark.parametrize(
    "content", ["What is new?", "Read http://127.0.0.1/private", 'Explain "read https://example.com/"']
)
def test_render_mode_requires_its_own_explicit_public_page(rendered, content):
    with TestClient(app) as api:
        route = conversation(api)
        queued = send(api, route, content=content)
        step()
        result = api.get("/api/runs/" + queued["id"]).json()
        assert result["status"] == "failed" and "explicit public page URL" in result["error_message"]
        assert not rendered[0] and not rendered[1]


def test_first_send_receipt_does_not_duplicate_rendering_on_replay(rendered):
    with TestClient(app) as api:
        body = turn(content="Read https://example.com/", web_search={"enabled": True, "render_pages": True})
        response = api.post("/api/chat/turns", json=body)
        assert response.status_code == 202, response.text
        receipt = response.json()
        assert api.post("/api/chat/turns", json=body).json() == receipt
        step()
        replay = api.post("/api/chat/turns", json=body).json()
        assert replay["conversation_id"] == receipt["conversation_id"]
        assert replay["run"]["id"] == receipt["run"]["id"]
        assert len(rendered[1]) == 1
        answer = api.get("/api/chat/conversations/" + receipt["conversation_id"]).json()["messages"][-1]
        assert answer["run_status"] == "succeeded", answer


def test_rendered_page_can_ground_an_image_brief_without_using_search_snippets(rendered):
    with TestClient(app) as api:
        route = conversation(api, "orchestrator")
        send(api, route, action="image.generate")
        with session_factory()() as session:
            # Dispatcher, browser, then the text brief. Leave actual GPU generation queued.
            for _ in range(3):
                assert tick(session, "rendered-image-brief") is not None
        detail = api.get(route).json()
        image = detail["active_run"]
        assert image["executor_type"] == "photo_pipe", detail
        source = detail["messages"][-1]["metadata"]["page_read"]
        assert image["metadata"]["page_read_artifact_id"] == source["artifact_id"]
        assert "network_read" not in image["effective_permissions"]
        assert len(rendered[1]) == 1 and len(rendered[0]) == 1


def test_a_failed_new_page_blocks_accidental_reuse_of_the_previous_site(rendered, monkeypatch):
    with TestClient(app) as api:
        route = conversation(api)
        send(api, route)
        step()
        fake_runner(monkeypatch, exit_code=1)
        send(api, route, content="Read https://other.example.com/")
        step()
        queued = send(api, route, content="Make it an Instagram prompt", web_search={"enabled": True})
        assert queued["parameters"]["page_read"] is None


def test_pre_render_option_receipt_replays_but_cannot_gain_a_browser_grant(rendered):
    import hashlib
    import json

    from app.chat import TurnBody
    from app.models import ChatTurnRequest

    body = turn(content="Read https://example.com/", web_search={"enabled": True})
    with TestClient(app) as api:
        first = api.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        # Simulate the canonical receipt from the deployed schema before render_pages existed.
        legacy = TurnBody.model_validate(body).model_dump(mode="json")
        for key in [
            "expected_provider_version",
            "reasoning",
            "continuation",
            "media",
            "github",
            "project_defaults",
        ]:
            legacy.pop(key)
        legacy["web_search"].pop("render_pages", None)
        with session_factory()() as session:
            receipt = session.get(ChatTurnRequest, body["client_request_id"])
            receipt.payload_hash = hashlib.sha256(
                json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            session.commit()
        replay = api.post("/api/chat/turns", json=body)
        assert replay.status_code == 202, replay.text
        assert replay.json()["run"]["id"] == first.json()["run"]["id"]
        explicit_off = {**body, "web_search": {"enabled": True, "render_pages": False}}
        assert api.post("/api/chat/turns", json=explicit_off).status_code == 202
        changed_grant = {**body, "web_search": {"enabled": True, "render_pages": True}}
        assert api.post("/api/chat/turns", json=changed_grant).status_code == 409
        assert not rendered[1]
