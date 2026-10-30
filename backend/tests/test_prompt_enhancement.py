"""Opt-in descriptive enhancement shares the durable local preparation graph."""

import json
from uuid import uuid4

from app.api import app
from app.image_schema import ImageRequest
from app.media_translation import RECEIPT
from app.media_translation_text import TranslationOptions
from fastapi.testclient import TestClient
from test_media_translation import fake as fake
from test_media_translation import read, settings, submit, work


def test_default_false_preserves_legacy_serialized_request_identity():
    legacy = {"mode": "inherit", "review": False, "protected_terms": []}
    assert TranslationOptions().model_dump() == legacy
    assert TranslationOptions(enhance=False).model_dump() == legacy
    assert (
        ImageRequest(mode="t2i", prompt="A bicycle", translation={"enhance": False}).model_dump()[
            "translation"
        ]
        == legacy
    )


def test_enhancement_runs_locally_even_when_translation_is_off_and_reaches_generator(fake, monkeypatch):
    calls, outputs = fake

    async def enhance(session, parameters):
        calls.append(parameters)
        assert parameters["provider"] == "local-openai-compatible" and parameters["location"] == "local"
        assert "Preserve each field's original language" in parameters["system_prompt"]
        fields = json.loads(parameters["messages"][-1]["content"])
        yield json.dumps({key: text + ", delikatne światło poranka" for key, text in fields.items()})

    monkeypatch.setattr("app.media_translation.completion_stream", enhance)
    with TestClient(app) as client:
        settings(client, enabled=False)
        media = submit(client, translation={"mode": "off", "enhance": True})
        receipt = media["metadata"][RECEIPT]
        assert receipt["policy"]["operation"] == "enhance"
        assert receipt["policy"]["target_language"] == "original"
        assert receipt["policy"]["enhancement_template"].endswith(":image:juggernaut:t2i")
        assert outputs == calls == []
        assert work() == receipt["preparation_run_id"]
        prepared = read(client, media["id"])
        assert prepared["parameters"]["prompt"] == "czerwony rower, delikatne światło poranka"
        assert prepared["metadata"][RECEIPT]["original"]["prompt"] == "czerwony rower"
        assert work() == media["id"]
        assert outputs[0]["prompt"] == prepared["parameters"]["prompt"]


def test_use_original_explicitly_bypasses_enhancement_on_recovery(fake):
    calls, outputs = fake
    with TestClient(app) as client:
        settings(client, enabled=False)
        source = submit(client, translation={"mode": "off", "enhance": True})
        assert work() == source["metadata"][RECEIPT]["preparation_run_id"]
        assert client.post("/api/runs/" + source["id"] + "/cancel").status_code == 200
        response = client.post(
            "/api/images/runs/" + source["id"] + "/retry",
            json={"translation": "original", "client_request_id": str(uuid4())},
        )
        assert response.status_code == 202, response.text
        retry = response.json()
        assert retry["parameters"]["prompt"] == "czerwony rower"
        assert work() == retry["id"]
        assert len(calls) == len(outputs) == 1
        assert outputs[0]["prompt"] == "czerwony rower"
