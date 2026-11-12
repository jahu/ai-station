"""Model matching reads personal defaults and cannot authorize foreign inputs."""

from app.db import control_session_factory
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_assistant_controller import model as model
from test_image_models import registered


def test_auto_preview_is_personal_and_does_not_enqueue_work(accounts):
    _, alice, bob = accounts
    with control_session_factory()() as session:
        model, _ = registered(session)
        identity = model.id
        session.commit()
    changed = alice.put("/api/images/defaults", json={"mode": "img2img", "choice": identity, "revision": 0})
    assert changed.status_code == 200, changed.text
    request = {"mode": "img2img", "prompt": "Make the lighting warmer", "reference_count": 1}
    first = alice.post("/api/images/models/recommendation", json=request)
    second = bob.post("/api/images/models/recommendation", json=request)
    assert first.status_code == second.status_code == 200
    assert first.json()["choice"]["id"] == identity and first.json()["revision"] == 1
    assert second.json()["choice"]["id"] == "qwen" and second.json()["revision"] == 0
    assert alice.get("/api/runs").json() == bob.get("/api/runs").json() == []


def test_auto_does_not_grant_another_accounts_source_artifact(accounts):
    _, alice, bob = accounts
    image, _ = upload(alice, "green")
    result = bob.post(
        "/api/images/runs",
        json={
            "mode": "img2img",
            "edit_prompt": "Remove the book",
            "input_artifact_ids": [image],
            "model_selection": "auto",
        },
    )
    assert result.status_code == 404, result.text
    assert bob.get("/api/runs").json() == []


def station_defaults():
    from app.models import Setting

    with control_session_factory()() as session:
        model, _ = registered(session)
        identity = model.id
        value = {"revision": 5, "choices": {mode: identity for mode in ("t2i", "img2img", "recompose")}}
        session.add(
            Setting(key="image_model_defaults", value={**value, "unrelated_private_field": "never expose"})
        )
        session.add(Setting(key="unrelated_private_setting", value={"secret": "never expose"}))
        session.commit()
    return identity


def test_unconfigured_accounts_inherit_station_models_and_first_override_preserves_other_modes(accounts):
    from app.models import UserSetting
    from sqlalchemy import select

    _, alice, bob = accounts
    identity = station_defaults()
    for browser in (alice, bob):
        response = browser.get("/api/images/models")
        assert response.status_code == 200, response.text
        defaults = response.json()["defaults"]
        assert defaults == {
            "revision": 5,
            "choices": {"t2i": identity, "img2img": identity, "recompose": identity, "upscale": "realesrgan"},
        }
        assert "never expose" not in response.text
    with control_session_factory()() as session:
        assert not list(session.scalars(select(UserSetting).where(UserSetting.key == "image_model_defaults")))
    changed = alice.put("/api/images/defaults", json={"mode": "recompose", "choice": "qwen", "revision": 5})
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 6
    assert changed.json()["choices"] == {
        "t2i": identity,
        "img2img": identity,
        "recompose": "qwen",
        "upscale": "realesrgan",
    }
    assert bob.get("/api/images/models").json()["defaults"]["choices"]["recompose"] == identity
    assert (
        alice.put(
            "/api/images/defaults", json={"mode": "recompose", "choice": identity, "revision": 5}
        ).status_code
        == 409
    )


def test_station_revision_changes_are_checked_before_the_first_personal_write(accounts):
    from app.models import Setting, UserSetting
    from sqlalchemy import select

    _, alice, _ = accounts
    identity = station_defaults()
    assert alice.get("/api/images/models").json()["defaults"]["revision"] == 5
    with control_session_factory()() as session:
        row = session.get(Setting, "image_model_defaults")
        row.value = {**row.value, "revision": 6}
        session.commit()
    response = alice.put("/api/images/defaults", json={"mode": "recompose", "choice": "qwen", "revision": 5})
    assert response.status_code == 409
    assert alice.get("/api/images/models").json()["defaults"]["choices"]["recompose"] == identity
    with control_session_factory()() as session:
        assert not list(session.scalars(select(UserSetting).where(UserSetting.key == "image_model_defaults")))


def test_new_controller_freezes_the_inherited_choice_and_keeps_old_requests_after_an_override(
    accounts, model
):
    from app.models import Run
    from test_assistant_controller import submit

    _, alice, _ = accounts
    identity = station_defaults()
    first = submit(alice, "Create two separate pictures")
    with control_session_factory()() as session:
        root = session.get(Run, first["run"]["id"])
        assert root.parameters["controller_image_catalog"]["defaults"]["choices"]["recompose"] == identity
    changed = alice.put("/api/images/defaults", json={"mode": "recompose", "choice": "qwen", "revision": 5})
    assert changed.status_code == 200
    second = submit(alice, "Create another picture")
    with control_session_factory()() as session:
        old = session.get(Run, first["run"]["id"])
        new = session.get(Run, second["run"]["id"])
        assert old.parameters["controller_image_catalog"]["defaults"]["choices"]["recompose"] == identity
        assert new.parameters["controller_image_catalog"]["defaults"]["choices"]["recompose"] == "qwen"


def test_unavailable_inherited_model_does_not_silently_switch_back_to_qwen(accounts):
    from app.models import ModelFile
    from sqlalchemy import select

    _, alice, _ = accounts
    station_defaults()
    with control_session_factory()() as session:
        file = session.scalar(select(ModelFile).where(ModelFile.filename == "lustify.gguf"))
        file.availability = "missing"
        session.commit()
    response = alice.post("/api/images/runs", json={"mode": "t2i", "prompt": "A cabinet"})
    assert response.status_code == 409, response.text
    assert alice.get("/api/runs").json() == []


def test_malformed_station_configuration_is_not_treated_as_an_absent_preference(accounts):
    from app.models import Setting

    _, alice, _ = accounts
    with control_session_factory()() as session:
        session.add(Setting(key="image_model_defaults", value=None))
        session.commit()
    response = alice.get("/api/images/models")
    assert response.status_code == 409, response.text
    assert alice.get("/api/runs").json() == []
