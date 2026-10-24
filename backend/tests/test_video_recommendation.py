"""Recommendations freeze into new Runs without rewriting old requests or scopes."""

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import memory_scope
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.assistant import VideoScope
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.runner_client import RunnerClient, RunnerUnavailable
from app.video import capabilities, recommended_profile
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_video import bridge as bridge
from test_video import image


def profile(**changes):
    return {
        "available": True,
        "memory_estimate_mib": 16000,
        "memory_profiles": [{"id": "bounded_11g", "available": True, "ram_mib": 11264}],
        **changes,
    }


@pytest.mark.parametrize(
    "available,expected",
    [
        (13000, "bounded_11g"),
        (5000, "bounded_11g"),
        (17024, "default"),
        (24000, "default"),
        (None, "default"),
        (True, "default"),
        (float("nan"), "default"),
        (float("inf"), "default"),
        (-1, "default"),
    ],
)
def test_recommendation_uses_measured_finite_ram_and_preserves_standard_when_it_fits(available, expected):
    assert recommended_profile(profile(), available) == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"available": False},
        {"memory_profiles": []},
        {"memory_estimate_mib": None},
        {"memory_estimate_mib": 9000},
    ],
)
def test_unavailable_or_incompatible_profile_never_becomes_a_recommendation(changes):
    assert recommended_profile(profile(**changes), 13000) == "default"


def test_legacy_capabilities_do_not_trigger_an_unnecessary_hardware_query(monkeypatch):
    monkeypatch.setattr(RunnerClient, "request", lambda *a: profile(memory_profiles=[]))
    monkeypatch.setattr(RunnerClient, "hardware", lambda *a: pytest.fail("Legacy setup queried hardware"))
    assert capabilities()["recommended_memory_profile"] == "default"


def test_transient_hardware_failure_retains_available_engine_and_standard(monkeypatch):
    monkeypatch.setattr(RunnerClient, "request", lambda *a: profile())

    def unavailable(*args):
        raise RunnerUnavailable("Transient fixture observation failure")

    monkeypatch.setattr(RunnerClient, "hardware", unavailable)
    result = capabilities()
    assert result["available"] and result["recommended_memory_profile"] == "default"


def test_absent_video_choice_keeps_exact_legacy_chat_scope_identity():
    assert VideoScope(duration_seconds=5).model_dump(mode="json") == {
        "duration_seconds": 5,
        "composition_mode": "continuous",
    }
    assert (
        VideoScope(duration_seconds=5, memory_profile="default").model_dump()["memory_profile"] == "default"
    )


@pytest.fixture
def recommended_bridge(bridge, monkeypatch):
    monkeypatch.setenv("AI_STATION_WAN_BOUNDED_PROFILE", "true")
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    clear_settings_cache()
    original = host_app.video_capabilities
    monkeypatch.setattr(host_app, "video_capabilities", lambda: {**original(), "memory_estimate_mib": 16000})
    monkeypatch.setattr(
        host_app, "collect", lambda *a: {"gpus": [{"index": 7}], "memory": {"available_mib": 13000}}
    )
    return bridge


@pytest.mark.parametrize(
    "media,bounded",
    [
        (None, True),
        ({"duration_seconds": 5}, True),
        ({"duration_seconds": 5, "memory_profile": "default"}, False),
    ],
)
def test_new_chat_video_uses_frozen_recommendation_and_honors_explicit_standard(
    recommended_bridge, media, bounded
):
    with TestClient(app) as client:
        cid = client.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
        ).json()["id"]
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Wygeneruj wideo spokojnego wybrzeża",
                "action": "video.generate",
                **({"media": media} if media else {}),
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as db:
            tick(db, "recommend-video")
            children = list(db.scalars(select(Run).where(Run.executor_type == "wan_video")))
            assert children
            for child in children:
                assert child.status == "queued"
                assert (child.parameters.get("memory_profile") == "bounded_11g") is bounded
                if bounded:
                    assert child.requested_resources == {"ram_mib": 11264}
                    assert child.parameters["profile_observation"]
            # Verify the actual typed dispatch shape without launching another
            # GPU sample: native execution/scopes are unchanged from PR #396.
            from ai_station_runner.video import VideoRequest as NativeVideoRequest
            from app.video import VideoExecutor

            class Capture:
                def request(self, method, path, payload):
                    assert method == "POST" and path == "/v1/runs/video"
                    body = NativeVideoRequest.model_validate(payload)
                    assert body.memory_profile == ("bounded_11g" if bounded else "default")
                    if bounded:
                        assert payload["profile_observation"] == children[0].parameters["profile_observation"]
                    return {"status": "recorded-fixture"}

            VideoExecutor()._start(Capture(), children[0], "7", "unused-output.mp4")
            if media:
                plan = children[0].task.metadata_json["media_plan"]
                assert (plan["request"].get("memory_profile") == "bounded_11g") is bounded
        messages = client.get(f"/api/chat/conversations/{cid}").json()["messages"]
        assert ("reduced-RAM landscape" in messages[-1]["content"]) is bounded


def test_ordinary_image_animation_retains_standard_instead_of_auto_selecting_text_only_profile(
    recommended_bridge,
):
    with TestClient(app) as client:
        source = image(client)
        cid = client.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
        ).json()["id"]
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Animate this photo",
                "action": "video.generate",
                "image_artifact_ids": [source["id"]],
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as db:
            tick(db, "recommend-image-video")
            child = db.scalar(select(Run).where(Run.executor_type == "wan_video"))
            assert child and "memory_profile" not in child.parameters
