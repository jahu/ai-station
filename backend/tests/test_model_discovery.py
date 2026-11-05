"""Guided discovery remains a bounded, private metadata workload, never a download."""

from uuid import uuid4

import pytest
from app import model_hub
from app.api import app
from app.hub_sources import parse_source
from app.model_discovery import STARTING_POINTS
from fastapi.testclient import TestClient
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_hub_comparisons import plan_request, work
from test_hub_comparisons import sources as sources


def enqueue(api, **changes):
    return api.post(
        "/api/model-hub/recommendations",
        json={"client_request_id": str(uuid4()), **changes},
    )


def test_enqueues_only_is_idempotent_and_reuses_ranked_source_for_planning(sources):
    with TestClient(app) as api:
        request = {"client_request_id": str(uuid4()), "context_target": 131072}
        pending = api.post("/api/model-hub/recommendations", json=request)
        assert pending.status_code == 202, pending.text
        assert not sources["calls"]
        again = api.post("/api/model-hub/recommendations", json=request)
        assert again.json()["id"] == pending.json()["id"]
        assert (
            api.post("/api/model-hub/recommendations", json={**request, "capability": "video"}).status_code
            == 409
        )
        work()
        run = api.get("/api/runs/" + pending.json()["id"]).json()
        assert run["status"] == "succeeded", run
        report = run["metadata"]["source_inspection"]
        assert report["kind"] == "comparison" and report["capability"] == "chat"
        assert report["context_target"] == 131072 and report["order"] == "popular"
        assert len(sources["calls"]) == len(report["items"]) == 3
        assert report["items"][0]["suitability"] == "fits"
        assert report["items"][-1]["suitability"] == "does_not_fit"
        assert report["no_weights_downloaded"] and report["metadata_only"]
        assert "search_run_id" not in report
        assert sum(bool(item.get("starting_point")) for item in report["items"]) == 1
        planned = api.post("/api/model-hub/plans", json=plan_request(run))
        assert planned.status_code == 202, planned.text
        work()
        assert api.get("/api/runs/" + planned.json()["id"]).json()["status"] == "succeeded"
        assert len(sources["calls"]) == 3


@pytest.mark.parametrize("capability", STARTING_POINTS)
def test_each_capability_has_a_pinned_specific_file_and_never_fits_an_unrelated_runtime(sources, capability):
    query, link = STARTING_POINTS[capability]
    source = parse_source(link)
    assert query and len(source.revision) == 40 and source.filename
    with TestClient(app) as api:
        pending = enqueue(api, capability=capability)
        assert pending.status_code == 202
        work()
        run = api.get("/api/runs/" + pending.json()["id"]).json()
        assert run["status"] == "succeeded", run
        report = run["metadata"]["source_inspection"]
    assert report["capability"] == capability and len(report["items"]) == 3
    if capability != "chat":  # Fixture intentionally supplies only a language graph.
        assert all(item["suitability"] == "unsupported" for item in report["items"])
        assert all("selected use" in item["summary"] for item in report["items"])


@pytest.mark.parametrize(
    "change", [{"capability": "shell"}, {"order": "best"}, {"context_target": 1}, {"download": True}]
)
def test_invalid_discovery_choices_do_not_start_work(sources, change):
    with TestClient(app) as api:
        assert enqueue(api, **change).status_code == 422
    assert not sources["calls"]


def test_recent_order_is_forwarded_and_search_failure_keeps_only_the_inspected_starting_point(
    sources, monkeypatch
):
    orders = []

    async def search(query, check, *, order):
        check()
        orders.append(order)
        raise ValueError("Publisher rate limit")

    monkeypatch.setattr(model_hub, "search_models", search)
    with TestClient(app) as api:
        pending = enqueue(api, order="recent")
        work()
        run = api.get("/api/runs/" + pending.json()["id"]).json()
    assert run["status"] == "succeeded", run
    report = run["metadata"]["source_inspection"]
    assert orders == ["recent"] and report["order"] == "recent"
    assert len(report["items"]) == 1 and report["items"][0]["starting_point"]
    assert "rate limit" in report["discovery_notice"]


@pytest.mark.parametrize("missing", ["hardware", "storage"])
def test_unknown_actual_resources_never_earn_a_green_recommendation(sources, missing):
    sources[missing] = {} if missing == "hardware" else None
    with TestClient(app) as api:
        pending = enqueue(api)
        work()
        run = api.get("/api/runs/" + pending.json()["id"]).json()
    assert run["status"] == "succeeded", run
    assert not any(row["suitability"] == "fits" for row in run["metadata"]["source_inspection"]["items"])


def test_stopping_before_or_during_discovery_publishes_no_authority(sources):
    with TestClient(app) as api:
        pending = enqueue(api).json()
        api.post("/api/runs/" + pending["id"] + "/cancel")
        work()
        assert not sources["calls"]
        pending = enqueue(api).json()
        sources["stop"] = lambda: api.post("/api/runs/" + pending["id"] + "/cancel")
        work()
        run = api.get("/api/runs/" + pending["id"]).json()
    assert run["status"] == "canceled" and "source_inspection" not in run["metadata"]


def test_discovery_administration_and_history_are_account_private(accounts, sources):
    owner, alice, bob = accounts
    assert enqueue(alice).status_code == 403
    pending = enqueue(owner).json()
    work()
    assert owner.get("/api/runs/" + pending["id"]).json()["status"] == "succeeded"
    assert alice.get("/api/runs/" + pending["id"]).status_code == 404
    assert bob.get("/api/runs/" + pending["id"]).status_code == 404
