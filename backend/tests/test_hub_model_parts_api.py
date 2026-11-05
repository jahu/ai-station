"""Part-set metadata survives private durable inspection without permitting partial install."""

from uuid import uuid4

from app import hub_sources, model_hub, model_variant_advice
from app.api import app
from app.db import control_session_factory
from app.models import ModelDefinition, ModelFile
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_account_private_api import private_app as private_app
from test_hub_model_parts import GiB, part
from test_hub_sources import document
from test_model_hub import work


def test_worker_persists_complete_part_set_and_partial_plan_refuses_without_any_weight_transfer(monkeypatch):
    rows = [part(1), part(2)]
    calls = []

    async def metadata(url, check):
        check()
        calls.append(url)
        return document(siblings=rows)

    async def no_config(report, check):
        # A split set is not a runtime profile; this test performs no inference/network.
        check()

    monkeypatch.setattr(hub_sources, "metadata_json", metadata)
    monkeypatch.setattr(model_variant_advice, "enrich_source", no_config)
    monkeypatch.setattr(model_hub.RunnerClient, "hardware", lambda self: {"gpus": []})
    monkeypatch.setattr(
        model_hub, "storage_info", lambda hardware: {"free_bytes": 10 * GiB, "headroom_bytes": GiB}
    )
    with TestClient(app) as api:
        response = api.post(
            "/api/model-hub/inspections",
            json={
                "client_request_id": str(uuid4()),
                "source": "https://huggingface.co/publisher/model/blob/main/" + rows[1]["rfilename"],
            },
        )
        assert response.status_code == 202, response.text
        assert not calls
        work()
        saved = api.get("/api/runs/" + response.json()["id"]).json()
        assert saved["status"] == "succeeded", saved
        report = saved["metadata"]["source_inspection"]
        assert report["no_weights_downloaded"] and len(report["files"]) == 1
        assert report["model_bundles"][0]["total_size_bytes"] == 16 * GiB
        assert report["files"][0]["assessment"]["disk"]["status"] == "insufficient"
        artifact = api.get("/api/artifacts/" + saved["metadata"]["inspection_artifact_id"] + "/file").json()
        assert artifact == report
        plan = api.post(
            "/api/model-hub/plans",
            json={
                "client_request_id": str(uuid4()),
                "inspection_run_id": saved["id"],
                "observation_sha256": report["observation_sha256"],
                "filename": rows[1]["rfilename"],
            },
        )
        assert plan.status_code == 202, plan.text
        work()
        result = api.get("/api/runs/" + plan.json()["id"]).json()
        assert result["status"] == "failed" and "complete compatible bundle plan" in result["error_message"]
        assert len(calls) == 1
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelFile)) == 0
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 0
