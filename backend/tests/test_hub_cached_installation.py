"""Complete-model cached plans do not charge already retained parts twice."""

from app import model_hub
from app.api import app
from fastapi.testclient import TestClient
from test_hub_split_installation import download, plan
from test_hub_split_installation import split_model as split_model
from test_logical_model_bindings import fresh_publisher_observation as fresh_publisher_observation
from test_model_setup import setup_bridge as setup_bridge


def test_complete_cached_plan_keeps_native_contract_and_rechecks_each_part(
    split_model, setup_bridge, monkeypatch
):
    with TestClient(app) as api:
        first = download(api, plan(api, split_model))
        assert first["run"]["status"] == "succeeded"
        monkeypatch.setattr(model_hub, "storage_info", lambda _: {"free_bytes": 522, "headroom_bytes": 512})
        current = plan(api, split_model)
        assessment = current["metadata"]["source_inspection"]["files"][0]["assessment"]
        total = sum(row["size_bytes"] for row in split_model["rows"])
        assert assessment["disk"]["model_bundle_bytes"] == total
        assert assessment["disk"]["reusable_model_bytes"] == total
        assert assessment["disk"]["model_weights_available"]
        assert assessment["disk"]["additional_bytes_upper_bound"] == 0
        assert assessment["disk"]["status"] == "file_fits"
        again = download(api, current)
        assert again["run"]["status"] == "succeeded", again["run"].get("error_message")
        assert again["model_key"] == first["model_key"]

        # Cached bytes never grant hardware authority after the station changes.
        setup_bridge["hardware"]["memory"]["total_mib"] = 1
        changed = plan(api, split_model)
        assessment = changed["metadata"]["source_inspection"]["files"][0]["assessment"]
        assert assessment["disk"]["model_weights_available"]
        assert assessment["hardware_status"] != "estimated_fit"
        from uuid import uuid4

        denied = api.post(
            "/api/model-hub/downloads",
            json={
                "client_request_id": str(uuid4()),
                "plan_run_id": changed["id"],
                "manifest_sha256": changed["metadata"]["source_inspection"]["manifest_sha256"],
                "license_accepted": True,
            },
        )
        assert denied.status_code == 409
