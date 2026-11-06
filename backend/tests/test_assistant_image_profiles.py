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


def test_reference_limit_is_checked_before_dispatch(session):
    model, _ = registered(session)
    root = SimpleNamespace(parameters={"controller_image_catalog": inventory(session)})
    with pytest.raises(ValueError, match="many references"):
        request_profile(
            session, root, SimpleNamespace(image_model=model.id), "recompose", ["one", "two", "three"]
        )


def test_deleted_definition_is_a_correctable_model_choice(session):
    model, _ = registered(session)
    selected = model.id
    root = SimpleNamespace(parameters={"controller_image_catalog": inventory(session)})
    session.delete(model)
    session.flush()
    with pytest.raises(ValueError, match="unavailable"):
        request_profile(session, root, SimpleNamespace(image_model=selected), "recompose", [])


def test_new_transform_uses_configured_editor_instead_of_reference_generator(session):
    image = source(session)
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="recompose", choice=model.id), session)
    root = SimpleNamespace(
        parameters={
            "controller_image_catalog": inventory(session),
            "controller_image_policy": "configured-default-v2",
        }
    )
    values = request_profile(session, root, SimpleNamespace(image_model=None), "recompose", [image.id])
    assert values["backend"] == "krea2" and values["model_id"] == model.id
    explicit = request_profile(session, root, SimpleNamespace(image_model="qwen"), "recompose", [image.id])
    assert explicit["backend"] == "qwen" and explicit["steps"] == 30 and explicit["cfg"] == 6
    recurring = request_profile(
        session, root, SimpleNamespace(image_model=None), "recompose", [image.id], inherit_source=True
    )
    assert recurring["backend"] == "qwen" and recurring["steps"] == 30


def test_reference_layout_is_explicit_bounded_and_not_confused_with_quality(session):
    from app.assistant_controller_tools import ImageOperation

    model, _ = registered(session)
    root = SimpleNamespace(
        parameters={
            "controller_image_catalog": inventory(session),
            "controller_image_policy": "configured-default-v2",
        }
    )
    args = ImageOperation(
        instruction="Show the object from a higher viewpoint",
        image_model=model.id,
        reference_layout="beside",
    )
    values = request_profile(session, root, args, "recompose", [])
    assert values["reference_layout"] == "beside"
    args.image_model = "qwen"
    with pytest.raises(ValueError, match="only to Krea2"):
        request_profile(session, root, args, "recompose", [])
    for layout in ("unknown", "../escape"):
        with pytest.raises(ValueError):
            ImageOperation(instruction="A new view", reference_layout=layout)


def test_recurring_definition_retains_selected_reference_controls(session):
    from uuid import uuid4

    from app.assistant_agent_media import image_definition

    model, _ = registered(session)
    image_id = str(uuid4())
    settings = image_definition(
        {
            "plan": {
                "goal": "Different views of the reference object",
                "media_kind": "image",
                "image_source": "supplied",
                "source_images": ["input:image:1"],
                "vary_results": True,
                "schedule": {"trigger": "interval", "interval_seconds": 900},
            },
            "images": [{"snapshot": {"id": image_id}}],
            "profile": {
                "backend": "krea2",
                "model_id": model.id,
                "reference_layout": "beside",
                "reference_strength": 2,
                "steps": 8,
                "cfg": 1,
            },
        },
        "test-model",
    )
    assert not settings.enabled and settings.interval_seconds == 900
    assert settings.media.request.reference_layout == "beside"
    assert settings.media.request.reference_strength == 2
    assert [str(value) for value in settings.media.request.input_artifact_ids] == [image_id]
