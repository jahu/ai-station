import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.media_translation import validate_media_translation
from app.media_translation_text import digest
from app.models import Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create as create_agent
from test_agent_media import drain as drain_agent
from test_agent_media import implemented_media as implemented_media
from test_agent_media import start as start_agent
from test_media_jobs import bridge as bridge
from test_media_translation import read, settings
from test_music import music_bridge as music_bridge


@pytest.fixture
def translator(monkeypatch):
    calls = []

    async def complete(session, params):
        calls.append(params)
        source = json.loads(params["messages"][-1]["content"])
        yield json.dumps(
            {
                key: value.replace("czerwony rower", "a red bicycle")
                .replace("spokojna muzyka", "calm music")
                .replace("bez rozmycia", "without blur")
                for key, value in source.items()
            }
        )

    monkeypatch.setattr("app.media_translation.completion_stream", complete)
    return calls


def work():
    with session_factory()() as db:
        return tick(db, "media-language-test")


def film(client, **values):
    response = client.post(
        "/api/media/jobs/video",
        json={
            "client_request_id": str(uuid4()),
            "prompt": "czerwony rower",
            "negative_prompt": "bez rozmycia",
            "duration_seconds": 5,
            "width": 128,
            "height": 128,
            "steps": 4,
            **values,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def stages(identifier):
    with session_factory()() as db:
        return list(db.get(Task, identifier).metadata_json["media_plan"]["segment_run_ids"])


def test_new_optional_fields_preserve_legacy_serialization():
    from app.music import MusicRequest
    from app.video_schema import VideoRequest

    assert "translation" not in VideoRequest(prompt="A scene").model_dump()
    assert "translation" not in MusicRequest(client_request_id=uuid4(), caption="Music").model_dump()


def test_music_translates_caption_but_keeps_lyrics_and_output_receipt(music_bridge, translator):
    with TestClient(app) as client:
        settings(client)
        body = {
            "client_request_id": str(uuid4()),
            "caption": "spokojna muzyka",
            "lyrics": "[Verse]\nPolskie słowa 123",
            "instrumental": False,
            "duration_seconds": 10,
            "seed": 42,
        }
        response = client.post("/api/audio/music/runs", json=body)
        assert response.status_code == 202, response.text
        media = response.json()
        work()
        assert len(translator) == 1
        prepared = read(client, media["id"])
        assert prepared["parameters"]["caption"] == "calm music"
        assert prepared["parameters"]["lyrics"] == body["lyrics"]
        assert set(json.loads(translator[0]["messages"][-1]["content"])) == {"caption"}
        work()
        assert read(client, media["id"])["status"] == "succeeded"
        artifacts = client.get("/api/artifacts", params={"run_id": media["id"]}).json()
        audio = next(item for item in artifacts if item["type"] == "audio")
        assert audio["metadata"]["prompt_translation"]["original"]["caption"] == body["caption"]
        assert audio["metadata"]["lyrics"] == body["lyrics"]
        assert audio["metadata"]["prompt_translation"]["artifact_id"] in audio["parent_artifact_ids"]


def test_repeated_film_prompts_use_one_review_and_real_cpu_composition(bridge, translator):
    with TestClient(app) as client:
        settings(client)
        view = film(client, translation={"review": True})
        ids = stages(view["task_id"])
        assert len(ids) == 2 and len(view["translation_consumer_run_ids"]) == 1
        work()
        first = read(client, ids[0])
        second = read(client, ids[1])
        assert first["parameters"]["prompt"] == second["parameters"]["prompt"] == "czerwony rower"
        assert (
            first["metadata"]["prompt_translation"]["review_run_id"]
            == second["metadata"]["prompt_translation"]["review_run_id"]
        )
        assert work() is None and not bridge
        review = read(client, first["metadata"]["prompt_translation"]["review_run_id"])
        response = client.post(
            "/api/generation/translations/" + review["id"] + "/review",
            json={
                "expected_hash": digest(review["parameters"]["effective"]),
                "effective": {"prompt": "A red bicycle at sunset", "negative_prompt": "without blur"},
            },
        )
        assert response.status_code == 200, response.text
        for _ in range(6):
            if work() is None:
                break
        assert len(translator) == 1
        final = client.get("/api/media/jobs/" + view["task_id"]).json()
        assert final["status"] == "succeeded", final
        for identifier in ids:
            actual = read(client, identifier)
            assert actual["parameters"]["prompt"] == "A red bicycle at sunset"
            with session_factory()() as db:
                validate_media_translation(db, db.get(Run, identifier))
        artifact = client.get("/api/artifacts/" + final["final_artifact_id"]).json()
        assert len(artifact["metadata"]["prompt_translations"]) == 1


def test_changed_group_member_fails_before_any_prompt_is_applied(bridge, translator):
    with TestClient(app) as client:
        settings(client)
        view = film(client)
        ids = stages(view["task_id"])
        with session_factory()() as db:
            secondary = db.get(Run, ids[1])
            secondary.parameters = {**secondary.parameters, "seed": 999}
            db.commit()
        work()
        prep = read(client, read(client, ids[0])["metadata"]["prompt_translation"]["preparation_run_id"])
        assert prep["status"] == "failed"
        assert all(read(client, identifier)["parameters"]["prompt"] == "czerwony rower" for identifier in ids)
        assert not bridge


def test_film_resume_reuses_text_or_explicitly_retries_frozen_policy(bridge, translator):
    with TestClient(app) as client:
        settings(client)
        view = film(client)
        work()
        client.post("/api/media/jobs/" + view["task_id"] + "/cancel")
        response = client.post(
            "/api/media/jobs/" + view["task_id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": 1},
        )
        assert response.status_code == 202, response.text
        for identifier in stages(view["task_id"]):
            actual = read(client, identifier)
            assert actual["parameters"]["prompt"] == "a red bicycle"
            with session_factory()() as db:
                validate_media_translation(db, db.get(Run, identifier))
        client.post("/api/media/jobs/" + view["task_id"] + "/cancel")
        settings(client, enabled=False, model="changed-default")
        body = {"client_request_id": str(uuid4()), "expected_revision": 2, "translation": "retry"}
        response = client.post("/api/media/jobs/" + view["task_id"] + "/resume", json=body)
        assert response.status_code == 202, response.text
        assert (
            client.post("/api/media/jobs/" + view["task_id"] + "/resume", json=body).json() == response.json()
        )
        assert (
            client.post(
                "/api/media/jobs/" + view["task_id"] + "/resume", json={**body, "translation": "original"}
            ).status_code
            == 409
        )
        with session_factory()() as db:
            pending = list(
                db.scalars(select(Run).where(Run.executor_type == "media_translate", Run.status == "queued"))
            )
            assert len(pending) == 1 and pending[0].parameters["model"] == "local-translator"
        work()
        assert len(translator) == 2


def test_failed_translation_can_resume_film_with_original(bridge, translator, monkeypatch):
    async def fail(*_):
        raise ValueError("Unavailable translator")
        yield

    monkeypatch.setattr("app.media_translation.completion_stream", fail)
    with TestClient(app) as client:
        settings(client)
        view = film(client)
        for _ in range(5):
            if work() is None:
                break
        assert (
            client.post(
                "/api/media/jobs/" + view["task_id"] + "/resume",
                json={"client_request_id": str(uuid4()), "expected_revision": 1},
            ).status_code
            == 409
        )
        body = {"client_request_id": str(uuid4()), "expected_revision": 1, "translation": "original"}
        response = client.post("/api/media/jobs/" + view["task_id"] + "/resume", json=body)
        assert response.status_code == 202, response.text
        for identifier in stages(view["task_id"]):
            actual = read(client, identifier)
            assert actual["parameters"]["prompt"] == "czerwony rower"
            assert actual["metadata"]["prompt_translation"]["status"] == "original"
            assert "artifact_id" not in actual["metadata"]["prompt_translation"]


def test_all_scene_preparations_and_reviews_gate_every_segment(bridge, translator):
    with TestClient(app) as client:
        settings(client)
        view = film(
            client,
            duration_seconds=4,
            composition_mode="shots",
            scenes=[
                {"prompt": "Pierwsza scena", "duration_seconds": 2},
                {"prompt": "Druga scena", "duration_seconds": 2},
            ],
            translation={"review": True},
        )
        ids = stages(view["task_id"])
        assert len(view["translation_consumer_run_ids"]) == 2
        assert work() and work()
        assert len(translator) == 2 and work() is None and not bridge
        first = read(client, ids[0])
        review = read(client, first["metadata"]["prompt_translation"]["review_run_id"])
        response = client.post(
            "/api/generation/translations/" + review["id"] + "/review",
            json={
                "expected_hash": digest(review["parameters"]["effective"]),
                "effective": review["parameters"]["effective"],
            },
        )
        assert response.status_code == 200, response.text
        assert work() == review["id"]
        assert work() is None and not bridge, "Another scene still needs review"
        client.post("/api/media/jobs/" + view["task_id"] + "/cancel")
        with session_factory()() as db:
            assert all(item.status in {"succeeded", "canceled"} for item in db.scalars(select(Run)))


def test_caption_limit_failure_has_explicit_original_retry_and_stable_receipt(
    music_bridge, translator, monkeypatch
):
    async def oversized(*_):
        yield json.dumps({"caption": "x" * 513})

    monkeypatch.setattr("app.media_translation.completion_stream", oversized)
    with TestClient(app) as client:
        settings(client)
        response = client.post(
            "/api/audio/music/runs",
            json={"client_request_id": str(uuid4()), "caption": "spokojna muzyka", "duration_seconds": 10},
        )
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        work()
        work()
        assert read(client, identifier)["status"] == "failed"
        body = {"translation": "original", "client_request_id": str(uuid4())}
        retried = client.post("/api/generation/media/" + identifier + "/retry", json=body)
        assert retried.status_code == 202, retried.text
        assert retried.json()["parameters"]["caption"] == "spokojna muzyka"
        assert (
            client.post("/api/generation/media/" + identifier + "/retry", json=body).json()["id"]
            == retried.json()["id"]
        )
        assert (
            client.post(
                "/api/generation/media/" + identifier + "/retry", json={**body, "translation": "retry"}
            ).status_code
            == 409
        )
        work()
        assert read(client, retried.json()["id"])["status"] == "succeeded"


def test_short_video_translates_only_description_and_off_override_skips_work(bridge, translator):
    with TestClient(app) as client:
        settings(client)
        response = client.post(
            "/api/video/runs",
            json={
                "prompt": "czerwony rower",
                "negative_prompt": "bez rozmycia",
                "width": 128,
                "height": 128,
                "frames": 17,
                "steps": 4,
                "seed": 43,
            },
        )
        assert response.status_code == 202, response.text
        item = response.json()
        work()
        work()
        actual = read(client, item["id"])
        assert actual["status"] == "succeeded"
        assert (
            actual["parameters"]["prompt"] == "a red bicycle"
            and actual["parameters"]["negative_prompt"] == "without blur"
        )
        assert actual["parameters"]["seed"] == 43 and actual["parameters"]["frames"] == 17
        response = client.post(
            "/api/video/runs",
            json={
                "prompt": "czerwony rower",
                "width": 128,
                "height": 128,
                "frames": 17,
                "steps": 4,
                "translation": {"mode": "off"},
            },
        )
        assert response.status_code == 202, response.text
        assert "prompt_translation" not in response.json()["metadata"]
        work()
        assert len(translator) == 1


def test_agent_film_freezes_translation_after_publishing_its_source_provenance(
    implemented_media, bridge, translator
):
    with TestClient(app) as client:
        settings(client)
        agent = create_agent(
            client,
            kind="video",
            request={
                "prompt": "czerwony rower",
                "duration_seconds": 5,
                "width": 128,
                "height": 128,
                "steps": 4,
            },
        )
        root = start_agent(client, agent)
        with session_factory()() as db:
            drain_agent(db)
            runs = list(db.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(item.status == "succeeded" for item in runs), [
                (item.executor_type, item.status, item.error_message) for item in runs
            ]
            segments = [item for item in runs if item.executor_type == "wan_video"]
            assert len(segments) == 2 and len(translator) == 1
            assert all(item.parameters["prompt"] == "a red bicycle" for item in segments)
            for item in segments:
                validate_media_translation(db, item)
