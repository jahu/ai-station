from types import SimpleNamespace

import pytest
from app.assistant_image_profiles import inventory, request_profile
from app.image_models import DefaultsWrite, change_default
from app.models import Artifact
from app.runs import create_run, create_task
from app.state import RunStatus
from test_image_models import registered


def test_explicit_model_overrides_workspace_default_without_sampling_regression(session):
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="recompose", choice=model.id), session)
    root = SimpleNamespace(parameters={"controller_image_catalog": inventory(session)})
    selected = request_profile(session, root, SimpleNamespace(image_model="qwen"), "recompose", [])
    assert selected == {"backend": "qwen"}
    assert (
        request_profile(session, root, SimpleNamespace(image_model=None), "recompose", [])["model_id"]
        == model.id
    )


def source(session):
    task = create_task(session, title="Cabinet", prompt="A cabinet", capability="image.recompose")
    run = create_run(
        session,
        task,
        run_type="image",
        capability="image.recompose",
        executor_type="photo_pipe",
        execution_target="host",
        parameters={
            "mode": "recompose",
            "backend": "qwen",
            "width": 832,
            "height": 1216,
            "steps": 30,
            "cfg": 6,
            "seed": None,
        },
    )
    run.status = RunStatus.SUCCEEDED.value
    image = Artifact(
        artifact_type="image",
        mime_type="image/png",
        relative_path="artifacts/example.png",
        size_bytes=100,
        sha256="a" * 64,
        run_id=run.id,
    )
    session.add(image)
    session.flush()
    return image


def test_followup_preserves_actual_source_profile_over_different_workspace_default(session):
    image = source(session)
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="recompose", choice=model.id), session)
    root = SimpleNamespace(parameters={"controller_image_catalog": inventory(session)})
    values = request_profile(session, root, SimpleNamespace(image_model=None), "recompose", [image.id])
    assert values == {"backend": "qwen", "width": 832, "height": 1216, "steps": 30, "cfg": 6, "seed": None}


def test_changed_model_is_not_silently_replaced(session):
    model, _ = registered(session)
    root = SimpleNamespace(parameters={"controller_image_catalog": inventory(session)})
    model.metadata_json = {"image": {**model.metadata_json["image"], "presets": {"recompose": {"steps": 9}}}}
    with pytest.raises(ValueError, match="changed"):
        request_profile(session, root, SimpleNamespace(image_model=model.id), "recompose", [])


def test_legacy_root_keeps_original_wrapper_shape(session):
    assert (
        request_profile(
            session, SimpleNamespace(parameters={}), SimpleNamespace(image_model=None), "recompose", []
        )
        == {}
    )


def test_same_definition_with_replaced_weights_is_rejected(session):
    model, _ = registered(session)
    root = SimpleNamespace(parameters={"controller_image_catalog": inventory(session)})
    model.metadata_json = {"image": {**model.metadata_json["image"], "sha256": "c" * 64}}
    with pytest.raises(ValueError, match="changed"):
        request_profile(session, root, SimpleNamespace(image_model=model.id), "recompose", [])
