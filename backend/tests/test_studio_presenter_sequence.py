from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.models import Artifact, Run
from app.studio_render import StudioRenderExecutor
from fastapi.testclient import TestClient
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_studio_presenter import clip
from test_studio_render import draft, render
from test_studio_render import ready as ready


def selected(first, second):
    return {"clips": [{"media": first, "duration_frames": 15}, {"media": second, "duration_frames": 15}]}


def test_an_older_ready_renderer_cannot_acquire_an_unsupported_sequence(ready):
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        face = clip(client)
        response = render(client, row, revision, image, presenter=selected(face, face))
        assert response.status_code == 409 and "current Studio renderer" in response.text


@pytest.fixture
def sequences(monkeypatch):
    monkeypatch.setattr(
        "app.studio_render.capabilities",
        lambda: {"available": True, "ram_mib": 4352, "observation": "a" * 64, "max_presenter_clips": 32},
    )


def test_all_parts_are_frozen_deduplicated_and_protected_by_the_original_receipt(sequences):
    with TestClient(app) as client:
        row, revision = draft(client)
        image, _ = upload(client, "blue")
        first, second = clip(client), clip(client)
        presenter = selected(first, second)
        nonce = str(uuid4())
        response = render(client, row, revision, image, presenter=presenter, client_request_id=nonce)
        assert response.status_code == 202, response.text
        parameters = response.json()["parameters"]
        assert set(parameters["sources"]) == {image, first, second}
        assert "media" not in parameters["presenter"]
        assert (
            render(client, row, revision, image, presenter=presenter, client_request_id=nonce).json()["id"]
            == response.json()["id"]
        )
        assert (
            render(
                client, row, revision, image, presenter=selected(second, first), client_request_id=nonce
            ).status_code
            == 409
        )
        with session_factory()() as db:
            run = db.get(Run, response.json()["id"])
            StudioRenderExecutor().validate_inputs(db, run)
            db.get(Artifact, second).trashed_at = run.created_at
            db.commit()
            with pytest.raises(ValueError):
                StudioRenderExecutor().validate_inputs(db, run)


def test_each_sequence_source_remains_account_scoped(sequences, accounts):
    _, alice, bob = accounts
    row, revision = draft(alice)
    image, _ = upload(alice, "blue")
    mine, foreign = clip(alice), clip(bob)
    response = render(alice, row, revision, image, presenter=selected(mine, foreign))
    assert response.status_code == 422
