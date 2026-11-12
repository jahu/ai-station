import pytest
from app.api import app
from app.config import get_settings
from app.db import control_session_factory, session_factory
from app.models import Artifact, Run
from app.studio_render import RenderRequest, StudioRenderExecutor, native_request
from fastapi.testclient import TestClient
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_studio_render import draft, render, wave_source
from test_studio_render import ready as ready


def clip(client):
    identity, _ = upload(client, "green")
    # A synthetic source only; native codec/decode tests qualify real MP4 bytes.
    with control_session_factory()() as db:
        item = db.get(Artifact, identity)
        old = get_settings().data_dir / item.relative_path
        target = old.with_suffix(".mp4")
        old.rename(target)
        item.relative_path = target.relative_to(get_settings().data_dir).as_posix()
        item.artifact_type, item.mime_type = "video", "video/mp4"
        db.commit()
    return identity


def test_presenter_is_frozen_with_lineage_single_soundtrack_and_exact_receipt(ready):
    with TestClient(app) as client:
        image, _ = upload(client, "blue")
        presenter = clip(client)
        row, revision = draft(client, audio="voice_music")
        audio = wave_source(client)
        payload = {"media": presenter, "placement": "right"}
        result = render(client, row, revision, image, audio, presenter=payload)
        assert result.status_code == 202, result.text
        parameters = result.json()["parameters"]
        assert set(parameters["parent_artifact_ids"]) == {presenter, image, audio}
        assert parameters["composition"]["presenter"]["media"] == presenter
        with session_factory()() as db:
            run = db.get(Run, result.json()["id"])
            native = native_request(run)
            assert len(native["sources"]) == 3 and native["audio_artifact_id"] == audio
            StudioRenderExecutor().validate_inputs(db, run)
            source = db.get(Artifact, presenter)
            (get_settings().data_dir / source.relative_path).write_bytes(b"changed source")
            with pytest.raises(ValueError):
                StudioRenderExecutor().validate_inputs(db, run)


@pytest.mark.parametrize("metadata", [{"partial": True}, {"internal_media": True}])
def test_partial_presenter_is_rejected_before_queue(ready, metadata):
    with TestClient(app) as client:
        image, _ = upload(client, "blue")
        presenter = clip(client)
        row, revision = draft(client)
        with session_factory()() as db:
            db.get(Artifact, presenter).metadata_json = metadata
            db.commit()
        result = render(client, row, revision, image, presenter={"media": presenter})
        assert result.status_code == 422 and "complete take" in result.text


def test_presenter_ownership_and_media_type_are_checked(ready, accounts):
    _, alice, bob = accounts
    row, revision = draft(alice)
    image, _ = upload(alice, "blue")
    foreign = clip(bob)
    assert render(alice, row, revision, image, presenter={"media": foreign}).status_code == 422
    assert render(alice, row, revision, image, presenter={"media": image}).status_code == 422


def test_absent_presenter_preserves_old_export_receipt():
    from uuid import uuid4

    raw = dict(client_request_id=str(uuid4()), revision_id=str(uuid4()))
    assert "presenter" not in RenderRequest(**raw).model_dump(mode="json")
    assert RenderRequest(**raw).model_dump(mode="json") == RenderRequest(**raw, presenter=None).model_dump(
        mode="json"
    )
