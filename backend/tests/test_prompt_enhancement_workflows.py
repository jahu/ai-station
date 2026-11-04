"""Real typed workers/CPU media with tools-free fake prompt preparation."""

import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.media_translation_text import digest
from app.models import Run
from fastapi.testclient import TestClient
from test_avatars import avatar_bridge as avatar_bridge
from test_avatars import inputs
from test_media_jobs import avatar_sources
from test_media_jobs import bridge as bridge
from test_media_jobs import full_avatar_bridge as full_avatar_bridge
from test_media_language_workflows import film, stages, work
from test_media_translation import read, settings
from test_music import music_bridge as music_bridge

SUFFIX = ", with a coherent natural presentation"


@pytest.fixture
def enhancement(monkeypatch):
    calls = []

    async def complete(session, params):
        calls.append(params)
        assert params["provider"] == "local-openai-compatible" and params["location"] == "local"
        assert "tools" not in params
        fields = json.loads(params["messages"][-1]["content"])
        yield json.dumps(
            {key: value if key.startswith("negative") else value + SUFFIX for key, value in fields.items()}
        )

    monkeypatch.setattr("app.media_translation.completion_stream", complete)
    return calls


def drain():
    for _ in range(16):
        if work() is None:
            return
    raise AssertionError("The disposable workflow did not drain")


def test_music_enhances_only_caption_and_preserves_exact_lyrics(music_bridge, enhancement):
    with TestClient(app) as api:
        settings(api, enabled=False)
        words = "[Verse]\nDokładne słowa piosenki 123."
        response = api.post(
            "/api/audio/music/runs",
            json={
                "client_request_id": str(uuid4()),
                "caption": "A calm piano ballad",
                "lyrics": words,
                "instrumental": False,
                "duration_seconds": 10,
                "translation": {"mode": "off", "enhance": True},
            },
        )
        assert response.status_code == 202, response.text
        item = response.json()
        drain()
        completed = read(api, item["id"])
        assert completed["status"] == "succeeded", completed
        assert completed["parameters"]["caption"] == "A calm piano ballad" + SUFFIX
        assert completed["parameters"]["lyrics"] == words
        assert set(json.loads(enhancement[0]["messages"][-1]["content"])) == {"caption"}
        artifacts = api.get("/api/artifacts", params={"run_id": item["id"]}).json()
        audio = next(row for row in artifacts if row["type"] == "audio")
        assert audio["metadata"]["lyrics"] == words
        assert audio["metadata"]["prompt_translation"]["policy"]["operation"] == "enhance"


def test_full_film_shares_one_reviewed_preparation_before_native_segments(bridge, enhancement):
    with TestClient(app) as api:
        settings(api, enabled=False)
        job = film(api, translation={"mode": "off", "enhance": True, "review": True})
        identifiers = stages(job["task_id"])
        assert work()
        first = read(api, identifiers[0])
        review = read(api, first["metadata"]["prompt_translation"]["review_run_id"])
        assert len(enhancement) == 1 and work() is None and not bridge
        edited = {**review["parameters"]["effective"], "prompt": "A bicycle moving slowly through a garden"}
        response = api.post(
            "/api/generation/translations/" + review["id"] + "/review",
            json={"expected_hash": digest(review["parameters"]["effective"]), "effective": edited},
        )
        assert response.status_code == 200, response.text
        drain()
        completed = api.get("/api/media/jobs/" + job["task_id"]).json()
        assert completed["status"] == "succeeded", completed
        assert len(enhancement) == 1
        assert all(
            read(api, identity)["parameters"]["prompt"] == edited["prompt"] for identity in identifiers
        )
        result = api.get("/api/artifacts/" + completed["final_artifact_id"]).json()
        assert result["metadata"]["prompt_translations"][0]["policy"]["operation"] == "enhance"


@pytest.mark.parametrize("spoken", [False, True])
def test_short_echo_keeps_script_and_freezes_model_before_speech(avatar_bridge, enhancement, spoken):
    with TestClient(app) as api:
        settings(api, enabled=False)
        portrait, audio = inputs(api)
        body = {
            "image_artifact_id": portrait["id"],
            "audio_artifact_id": audio["id"],
            "prompt": "Natural portrait motion",
            "translation": {"mode": "off", "enhance": True, "review": True},
        }
        if spoken:
            body["speech_text"] = "Dokładnie te słowa mają zostać wypowiedziane."
        response = api.post("/api/avatars/runs", json=body)
        assert response.status_code == 202, response.text
        root = response.json()
        if spoken:
            settings(api, model="changed-after-submission")
            assert work() == root["id"]
            workflow = api.get("/api/avatars/runs/" + root["id"] + "/workflow").json()
            animation = next(row for row in workflow["steps"] if row["executor_type"] == "echomimic")
            assert read(api, root["id"])["parameters"]["text"] == body["speech_text"]
        else:
            animation = root
        assert work() == animation["metadata"]["prompt_translation"]["preparation_run_id"]
        assert enhancement[0]["model"] == "local-translator"
        prepared = read(api, animation["id"])
        review = read(api, prepared["metadata"]["prompt_translation"]["review_run_id"])
        assert work() is None
        response = api.post(
            "/api/generation/translations/" + review["id"] + "/review",
            json={
                "expected_hash": digest(review["parameters"]["effective"]),
                "effective": review["parameters"]["effective"],
            },
        )
        assert response.status_code == 200, response.text
        drain()
        actual = read(api, animation["id"])
        assert actual["status"] == "succeeded", actual
        assert actual["parameters"]["prompt"] == "Natural portrait motion" + SUFFIX
        assert actual["metadata"]["prompt_translation"]["policy"]["enhancement_template"].endswith(":echo")


@pytest.mark.parametrize("spoken", [False, True])
def test_full_echo_prepares_after_sources_are_frozen_and_composes(full_avatar_bridge, enhancement, spoken):
    with TestClient(app) as api:
        settings(api, enabled=False)
        body = {
            **avatar_sources(api),
            "prompt": "A person speaking naturally",
            "translation": {"mode": "off", "enhance": True},
        }
        if spoken:
            body["speech_text"] = "Keep these exact narration words."
        response = api.post("/api/media/jobs/avatar", json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        settings(api, model="changed-after-submission")
        drain()
        final = api.get("/api/media/jobs/" + job["task_id"]).json()
        assert final["status"] == "succeeded", final
        assert len(enhancement) == 1 and enhancement[0]["model"] == "local-translator"
        with session_factory()() as db:
            native = list(
                db.query(Run).filter(Run.task_id == job["task_id"], Run.executor_type == "echomimic")
            )
            assert native and all(
                row.parameters["prompt"] == "A person speaking naturally" + SUFFIX for row in native
            )
        result = api.get("/api/artifacts/" + final["final_artifact_id"]).json()
        assert result["metadata"]["prompt_translations"][0]["policy"]["operation"] == "enhance"


def test_full_echo_resume_reuses_prepared_prompt_without_another_model_call(
    full_avatar_bridge, enhancement, monkeypatch
):
    from ai_station_runner import app as native_app

    actual = native_app.start_avatar

    def unavailable(*args):
        raise ValueError("Synthetic unavailable renderer")

    monkeypatch.setattr(native_app, "start_avatar", unavailable)
    with TestClient(app) as api:
        settings(api, enabled=False)
        body = {
            **avatar_sources(api),
            "prompt": "A person speaking naturally",
            "translation": {"mode": "off", "enhance": True},
        }
        response = api.post("/api/media/jobs/avatar", json=body)
        assert response.status_code == 202, response.text
        task = response.json()["task_id"]
        drain()
        failed = api.get("/api/media/jobs/" + task).json()
        assert failed["status"] == "failed" and failed["resume_allowed"], failed
        monkeypatch.setattr(native_app, "start_avatar", actual)
        resumed = api.post(
            "/api/media/jobs/" + task + "/resume",
            json={"expected_revision": 1, "translation": "reuse", "client_request_id": str(uuid4())},
        )
        assert resumed.status_code == 202, resumed.text
        drain()
        final = api.get("/api/media/jobs/" + task).json()
        assert final["status"] == "succeeded", final
        assert len(enhancement) == 1


def test_full_echo_stop_cancels_review_and_future_generation(full_avatar_bridge, enhancement):
    with TestClient(app) as api:
        settings(api, enabled=False)
        body = {**avatar_sources(api), "translation": {"mode": "off", "enhance": True, "review": True}}
        response = api.post("/api/media/jobs/avatar", json=body)
        assert response.status_code == 202, response.text
        task = response.json()["task_id"]
        assert work()
        assert work() is None and not full_avatar_bridge
        canceled = api.post("/api/media/jobs/" + task + "/cancel")
        assert canceled.status_code == 200, canceled.text
        assert api.get("/api/media/jobs/" + task).json()["status"] == "canceled"
        assert work() is None and len(enhancement) == 1 and not full_avatar_bridge
