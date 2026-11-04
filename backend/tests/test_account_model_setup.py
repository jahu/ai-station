from app.db import control_session_factory
from app.models import Artifact, ModelFile, Run, User
from app.runner_client import RunnerClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_setup import request, work
from test_model_setup import setup_bridge as setup_bridge


def test_only_admin_can_prepare_models_and_download_history_stays_private(accounts, setup_bridge):
    owner, alice, bob = accounts
    body = request(setup_bridge["entry"])
    assert alice.post("/api/setup/downloads", json=body).status_code == 403
    result = owner.post("/api/setup/downloads", json=body)
    assert result.status_code == 202, result.text
    identity = result.json()["id"]
    assert alice.get("/api/setup/downloads").json() == []
    assert bob.get("/api/setup/downloads/" + identity).status_code == 404
    assert alice.post("/api/setup/downloads/" + identity + "/cancel").status_code == 403
    work()
    value = owner.get("/api/setup/downloads/" + identity).json()
    assert value["run"]["status"] == "succeeded", value
    assert bob.get("/api/runs/" + value["run"]["id"]).status_code == 404
    catalog = bob.get("/api/setup/catalog").json()
    assert catalog["can_prepare"] is False
    assert catalog["entries"][0]["model_file_id"] == value["model_file_id"]
    assert bob.get("/api/models/" + value["model_file_id"]).status_code == 200
    definitions = bob.get("/api/models/definitions").json()
    assert definitions["items"][0]["last_verify_run_id"] is None


def test_demoted_administrator_cannot_publish_shared_files_after_transfer(
    accounts, setup_bridge, monkeypatch
):
    owner, _, _ = accounts
    original = RunnerClient.verify_model

    def demote(self, payload):
        result = original(self, payload)
        with control_session_factory()() as db:
            run = db.get(Run, payload["run_id"])
            db.get(User, run.owner_id).is_admin = False
            db.commit()
        return result

    monkeypatch.setattr(RunnerClient, "verify_model", demote)
    result = owner.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
    assert result.status_code == 202, result.text
    work()
    with control_session_factory()() as db:
        assert db.get(Run, result.json()["run"]["id"]).status == "canceled"
        assert not list(db.scalars(select(ModelFile)))
        assert not list(db.scalars(select(Artifact)))
