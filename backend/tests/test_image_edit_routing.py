"""Auto resolves once; explicit checkpoint selection retains authority."""

from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.image_edit_routing import structural_intent
from app.image_models import DefaultsWrite, change_default, resolve_request
from app.image_schema import ImageRequest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_image_models import registered
from test_images import bridge as bridge
from test_images import upload


@pytest.mark.parametrize(
    "prompt,reason",
    [
        ("Remove the book from her hand", "object_removal"),
        ("Usuń przedmiot z ręki", "object_removal"),
        ("Please change her pose", "pose"),
        ("Zmień pozę na siedzącą", "pose"),
        ("Make the woman sit on the bench", "pose"),
        ("Obróć głowę w lewo", "pose"),
        ("Move the bicycle to face left", "pose"),
        ("Do not remove the book. Change the lighting", None),
        ("Nie zmieniaj pozy, rozjaśnij zdjęcie", None),
        ('Keep the text "remove the book". Change the colors', None),
        ("> Remove the book\nMake the lighting warmer", None),
        ("Change her clothing to a blue jacket", None),
        ("Keep the words 'remove the book' intact", None),
        ("Remove noise and make colors warmer", None),
        ("No need to remove the book", None),
        ("Do not change the background, remove the book", "object_removal"),
        ("Don't remove the book but change her pose", "pose"),
    ],
)
def test_only_active_structural_edit_intent_selects_qwen(prompt, reason):
    assert structural_intent(prompt) == reason


def automatic(prompt, **values):
    return ImageRequest(
        mode="img2img", edit_prompt=prompt, input_artifact_ids=[uuid4()], model_selection="auto", **values
    )


def test_auto_resolves_structural_edits_to_qwen_and_other_edits_to_personal_default(session):
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="img2img", choice=model.id), session)
    structural, snapshot = resolve_request(session, automatic("Remove the red book"))
    assert structural.backend == "qwen" and snapshot is None and structural.steps == 30
    assert structural._selection["reason"] == "object_removal"
    assert structural.prompt_style == "instruction"
    color, snapshot = resolve_request(session, automatic("Make the lighting warmer"))
    assert color.backend == "krea2" and str(color.model_id) == model.id and color.steps == 8
    assert snapshot["definition_id"] == model.id
    assert color.model_selection is None and color._selection["revision"] == 1


def test_explicit_lustify_selection_is_never_overridden_by_structural_intent(session):
    model, _ = registered(session)
    request = ImageRequest(
        mode="img2img",
        backend="krea2",
        model_id=model.id,
        edit_prompt="Remove the book",
        input_artifact_ids=[uuid4()],
    )
    resolved, snapshot = resolve_request(session, request)
    assert resolved.backend == "krea2" and snapshot["definition_id"] == model.id
    assert resolved._selection is None


def test_auto_retains_the_configured_qwen_checkpoint_instead_of_replacing_its_weights(session):
    model, _ = registered(session)
    model.metadata_json = {"image": {**model.metadata_json["image"], "backend": "qwen"}}
    change_default(DefaultsWrite(revision=0, mode="img2img", choice=model.id), session)
    resolved, snapshot = resolve_request(session, automatic("Remove the book"))
    assert resolved.backend == "qwen" and snapshot["definition_id"] == model.id
    assert resolved._selection["choice"]["id"] == model.id


def test_auto_checks_preview_revision_and_reference_capacity(session):
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="img2img", choice=model.id), session)
    with pytest.raises(HTTPException) as error:
        resolve_request(session, automatic("Remove the book", model_selection_revision=0))
    assert error.value.status_code == 409
    change_default(DefaultsWrite(revision=1, mode="recompose", choice=model.id), session)
    request = ImageRequest(
        mode="recompose",
        prompt="Combine these references",
        input_artifact_ids=[uuid4() for _ in range(3)],
        model_selection="auto",
    )
    resolved, _ = resolve_request(session, request)
    assert resolved.backend == "qwen" and resolved._selection["reason"] == "reference_capacity"


def test_preview_is_read_only_and_auto_retry_keeps_frozen_selection(bridge):
    with TestClient(app) as api:
        preview = api.post(
            "/api/images/models/recommendation",
            json={"mode": "img2img", "prompt": "Remove the book", "reference_count": 1},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["choice"]["id"] == "qwen"
        assert api.get("/api/runs").json() == []
        source = upload(api)
        response = api.post(
            "/api/images/runs",
            json={
                "mode": "img2img",
                "edit_prompt": "Remove the book",
                "input_artifact_ids": [source["id"]],
                "model_selection": "auto",
                "model_selection_revision": 0,
                "gpu": "7",
                "prompt_style": "instruction",
            },
        )
        assert response.status_code == 202, response.text
        first = response.json()
        assert first["metadata"]["image_model_selection"]["reason"] == "object_removal"
        assert "model_selection" not in first["parameters"]
        assert api.post("/api/runs/" + first["id"] + "/cancel").status_code == 200
        retry = api.post("/api/images/runs/" + first["id"] + "/retry")
        assert retry.status_code == 202, retry.text
        assert retry.json()["metadata"]["image_model_selection"] == first["metadata"]["image_model_selection"]
        with session_factory()() as db:
            assert tick(db, "auto-image") == retry.json()["id"]
        result = api.get("/api/runs/" + retry.json()["id"]).json()
        assert result["status"] == "succeeded", result
        artifacts = api.get("/api/artifacts", params={"run_id": result["id"]}).json()
        assert artifacts[0]["metadata"]["image_model_selection"]["choice"]["id"] == "qwen"


@pytest.mark.parametrize(
    "values",
    [
        {"backend": "qwen"},
        {"prompt_style": "pipeline"},
        {"model_id": str(uuid4())},
        {"mode": "t2i", "prompt": "A bicycle", "input_artifact_ids": []},
        {"reference_strength": 2},
        {"model_selection": None, "model_selection_revision": 0},
    ],
)
def test_auto_never_accepts_a_conflicting_explicit_model_or_backend_controls(values):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImageRequest.model_validate(
            {
                "mode": "img2img",
                "edit_prompt": "Remove the book",
                "input_artifact_ids": [str(uuid4())],
                "model_selection": "auto",
                **values,
            }
        )


def test_absent_auto_retains_legacy_serialization():
    value = ImageRequest(mode="t2i", prompt="A bicycle").model_dump()
    assert "model_selection" not in value and "model_selection_revision" not in value


def test_saved_auto_intent_roundtrips_without_freezing_another_models_defaults(session):
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="img2img", choice=model.id), session)
    original = automatic("Make the lighting warmer")
    saved = original.model_dump(mode="json")
    assert saved["prompt_style"] == "instruction"
    assert not {"backend", "steps", "max_side", "model_id"} & saved.keys()
    restored = ImageRequest.model_validate(saved)
    for request in (original, restored):
        resolved, _ = resolve_request(session, request)
        assert resolved.backend == "krea2" and resolved.steps == 8 and resolved.max_side == 1024
