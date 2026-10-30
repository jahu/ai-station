"""Model matching reads personal defaults and cannot authorize foreign inputs."""

from app.db import control_session_factory
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
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
