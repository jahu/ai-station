"""Opt-in descriptive enhancement shares the durable local preparation graph."""

import json
from uuid import uuid4

import pytest
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


def test_malformed_enhancement_never_dispatches_generation(fake, monkeypatch):
    calls, outputs = fake

    async def broken(session, parameters):
        calls.append(parameters)
        yield json.dumps({"prompt": "replacement", "unexpected": "not permitted"})

    monkeypatch.setattr("app.media_translation.completion_stream", broken)
    with TestClient(app) as api:
        settings(api, enabled=False)
        item = submit(api, translation={"mode": "off", "enhance": True})
        preparation = item["metadata"][RECEIPT]["preparation_run_id"]
        assert work() == preparation
        assert read(api, preparation)["status"] == "failed"
        work()
        assert not outputs and read(api, item["id"])["parameters"]["prompt"] == "czerwony rower"


def test_retry_reuses_enhancement_model_and_keeps_translation_off(fake):
    calls, _ = fake
    with TestClient(app) as api:
        settings(api, enabled=False)
        source = submit(api, translation={"mode": "off", "enhance": True})
        work()
        assert api.post("/api/runs/" + source["id"] + "/cancel").status_code == 200
        settings(api, model="different-later-model", enabled=True)
        response = api.post(
            "/api/images/runs/" + source["id"] + "/retry",
            json={"translation": "retry", "client_request_id": str(uuid4())},
        )
        assert response.status_code == 202, response.text
        retry = response.json()
        work()
        assert len(calls) == 2 and calls[-1]["model"] == "local-translator"
        assert "Preserve each field's original language" in calls[-1]["system_prompt"]
        assert read(api, retry["id"])["metadata"][RECEIPT]["policy"]["translate_descriptions"] is False


@pytest.mark.parametrize("mode,count", [("img2img", 1), ("recompose", 2)])
def test_reference_image_enhancement_retains_input_order_and_operation_template(fake, mode, count):
    from test_images import png

    calls, outputs = fake
    with TestClient(app) as api:
        settings(api, enabled=False)
        sources = [
            api.post(
                "/api/images/uploads", files={"file": (f"source-{index}.png", png(), "image/png")}
            ).json()["id"]
            for index in range(count)
        ]
        item = submit(
            api,
            mode=mode,
            backend="qwen",
            seed=None,
            prompt="czerwony rower",
            edit_prompt="czerwony rower",
            input_artifact_ids=sources,
            translation={"mode": "off", "enhance": True},
        )
        work()
        work()
        completed = read(api, item["id"])
        assert completed["status"] == "succeeded", completed
        assert len(calls) == len(outputs) == 1
        assert outputs[0]["parent_artifact_ids"] == sources
        assert completed["metadata"][RECEIPT]["policy"]["enhancement_template"].endswith(
            ":image:qwen:" + mode
        )
