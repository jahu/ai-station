import pytest
from app.image_models import DefaultsWrite, change_default, choice, defaults, frozen_model, resolve_request
from app.image_schema import ImageRequest
from app.models import ModelDefinition, ModelFile
from fastapi import HTTPException


def registered(session):
    file = ModelFile(
        host_path="/configured/models/lustify.gguf",
        filename="lustify.gguf",
        size_bytes=100,
        mtime=1,
        format="gguf",
        category="image",
        availability="present",
    )
    session.add(file)
    session.flush()
    model = ModelDefinition(
        name="LUSTIFY Turbo Q4",
        category="image",
        file_id=file.id,
        status="registered",
        metadata_json={
            "image": {
                "backend": "krea2",
                "modes": ["t2i", "img2img", "recompose"],
                "sha256": "a" * 64,
                "profile_sha256": "b" * 64,
                "gpu_count": 2,
            }
        },
    )
    session.add(model)
    session.flush()
    return model, file


def test_legacy_choices_keep_existing_operation_limits(session):
    assert defaults(session)["choices"]["t2i"] == "qwen"
    assert choice(session, "juggernaut")["modes"] == ["t2i"]
    with pytest.raises(HTTPException):
        frozen_model(session, "juggernaut", "recompose")


def test_frozen_choice_retains_exact_checkpoint_and_runtime(session):
    model, file = registered(session)
    selected, frozen = frozen_model(session, model.id, "recompose")
    assert selected["maximum_references"] == 2
    file.host_path = "/configured/models/other.gguf"
    model.metadata_json = {"image": {"sha256": "c" * 64}}
    assert frozen["model_file"] == {
        "path": "/configured/models/lustify.gguf",
        "size": 100,
        "sha256": "a" * 64,
    }
    assert frozen["profile_sha256"] == "b" * 64


@pytest.mark.parametrize("change", ["missing", "unregistered", "sha", "profile"])
def test_explicit_bad_model_never_falls_back_to_qwen(session, change):
    model, file = registered(session)
    if change == "missing":
        file.availability = "missing"
    elif change == "unregistered":
        model.status = "unverified"
    elif change == "sha":
        model.metadata_json["image"]["sha256"] = ""
    else:
        model.metadata_json["image"]["profile_sha256"] = ""
    with pytest.raises(HTTPException):
        frozen_model(session, model.id, "t2i")


def test_per_operation_defaults_are_versioned_and_do_not_replace_other_modes(session):
    model, _file = registered(session)
    saved = change_default(DefaultsWrite(revision=0, mode="t2i", choice=model.id), session)
    assert saved["revision"] == 1
    assert saved["choices"]["t2i"] == model.id
    assert saved["choices"]["img2img"] == "qwen"
    with pytest.raises(HTTPException) as error:
        change_default(DefaultsWrite(revision=0, mode="img2img", choice="qwen"), session)
    assert error.value.status_code == 409
    assert defaults(session)["choices"]["t2i"] == model.id


def test_model_default_uses_its_own_presets_without_overwriting_explicit_controls(session):
    model, _ = registered(session)
    change_default(DefaultsWrite(revision=0, mode="t2i", choice=model.id), session)
    resolved, snapshot = resolve_request(session, ImageRequest(mode="t2i", prompt="A red bicycle", width=512))
    assert resolved.backend == "krea2"
    assert (resolved.width, resolved.height, resolved.steps, resolved.cfg) == (512, 1024, 8, 1)
    assert snapshot["definition_id"] == model.id
    explicit, _ = resolve_request(session, ImageRequest(mode="t2i", backend="qwen", prompt="A red bicycle"))
    assert explicit.backend == "qwen"
    assert explicit.steps == 35


def test_optional_model_fields_do_not_change_legacy_saved_settings():
    payload = ImageRequest(mode="t2i", prompt="A red bicycle").model_dump(mode="json")
    assert not set(payload) & {"model_id", "reference_strength", "reference_layout", "grounding_px"}


def test_krea_uses_normal_image_run_and_typed_native_payload(session):
    from types import SimpleNamespace

    from ai_station_runner.krea2_native import KreaRunRequest
    from app.images import create_image_run
    from app.photo_executor import PhotoPipeExecutor

    model, _ = registered(session)
    run = create_image_run(
        session, ImageRequest(mode="t2i", backend="krea2", model_id=model.id, prompt="A red bicycle")
    )
    assert run.executor_type == "photo_pipe"
    assert run.requested_resources == {"gpu": "auto", "gpu_count": 2, "ram_mib": 12288}
    assert run.parameters["steps"] == 8
    executor = PhotoPipeExecutor()
    assert executor.reserve_devices(session, run, [3, 7]) == "3"
    calls = []
    executor._start(
        SimpleNamespace(start_krea_image=lambda payload: calls.append(payload)), run, "3", "ignored"
    )
    native = KreaRunRequest.model_validate(calls[0])
    assert native.gpus == [3, 7]
    assert native.model_file.sha256 == "a" * 64
    assert native.options.cfg == 1
    assert native.options.prompt == "A red bicycle"


def test_image_catalog_is_read_only_and_defaults_change_no_existing_run(session):
    from app.image_models import image_choices
    from app.images import create_image_run

    first = create_image_run(session, ImageRequest(mode="t2i", prompt="A red bicycle"))
    model, _ = registered(session)
    listed = image_choices(session)
    assert any(item["id"] == model.id for item in listed["items"])
    change_default(DefaultsWrite(revision=0, mode="t2i", choice=model.id), session)
    second = create_image_run(session, ImageRequest(mode="t2i", prompt="A blue bicycle"))
    assert first.parameters["backend"] == "qwen"
    assert "image_model" not in first.parameters
    assert second.parameters["backend"] == "krea2"
    assert second.parameters["image_model"]["definition_id"] == model.id


def test_models_registry_identifies_image_adapter_without_llama_controls(session):
    from app.model_definitions import definition_dict

    model, file = registered(session)
    record = definition_dict(model, file)
    assert record["image_backend"] == "krea2"
    assert record["compatibility"]["runtime"] == "ComfyUI · Krea 2"
    assert record["compatibility"]["adapter"] == "host-media"
