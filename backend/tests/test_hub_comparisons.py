"""Hardware comparisons retain immutable observations and never authorize a download."""

import copy
from uuid import uuid4

import pytest
from app import model_hub
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.hub_comparisons import suitability
from app.model_setup import fingerprint
from app.models import ModelDefinition, ModelFile, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_variant_advice import source as language_source


def work():
    with control_session_factory()() as db:
        tick(db, "comparison-test")


@pytest.fixture
def sources(monkeypatch):
    state = {
        "calls": [],
        "failed": set(),
        "stop": None,
        "hardware": {
            "memory": {"total_mib": 65536},
            "gpus": [
                {"index": 7, "memory_total_mib": 12288, "memory_used_mib": 8192},
                {"index": 19, "memory_total_mib": 12288, "memory_used_mib": 0},
            ],
        },
        "storage": {"free_bytes": 100 * 1024**3, "headroom_bytes": 1024**3},
    }

    async def search(query, check):
        check()
        return {
            "kind": "search",
            "query": query,
            "files": [],
            "metadata_only": True,
            "items": [
                {
                    "repository": "publisher/" + name,
                    "source_url": "https://huggingface.co/publisher/" + name,
                    "pipeline_hint": "text-generation",
                    "downloads": 100 - index,
                }
                for index, name in enumerate(("huge", "usable", "also-usable", "not-inspected"))
            ],
        }

    async def inspect(source, check):
        check()
        state["calls"].append(source.repository)
        if state["stop"]:
            state["stop"]()
            check()
        if source.repository in state["failed"]:
            raise ValueError("Publisher access is required; no credentials sent")
        value = language_source()
        previous = value["repository"]
        value["repository"] = source.repository
        value["language_profile"]["source_repository"] = source.repository
        for field in ("source_url", "license_url"):
            value[field] = value[field].replace(previous, source.repository)
        for file in value["files"]:
            file["source_url"] = file["source_url"].replace(previous, source.repository)
            if source.repository.endswith("huge"):
                file["size_bytes"] *= 10
        return value

    monkeypatch.setattr(model_hub, "search_models", search)
    monkeypatch.setattr(model_hub, "inspect_source", inspect)
    monkeypatch.setattr(model_hub.RunnerClient, "hardware", lambda _: state["hardware"])
    monkeypatch.setattr(model_hub, "storage_info", lambda _: state["storage"])
    return state


def searched(api):
    response = api.post(
        "/api/model-hub/searches", json={"client_request_id": str(uuid4()), "query": "coding models"}
    )
    assert response.status_code == 202, response.text
    work()
    return api.get("/api/runs/" + response.json()["id"]).json()


def queued(api, search):
    response = api.post(
        "/api/model-hub/comparisons",
        json={
            "client_request_id": str(uuid4()),
            "search_run_id": search["id"],
            "observation_sha256": search["metadata"]["source_inspection"]["observation_sha256"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def compared(api):
    response = queued(api, searched(api))
    work()
    run = api.get("/api/runs/" + response["id"]).json()
    assert run["status"] == "succeeded", run
    return run


def plan_request(run, **changes):
    selected = run["metadata"]["source_inspection"]["items"][0]["observation"]
    return {
        "client_request_id": str(uuid4()),
        "inspection_run_id": run["id"],
        "observation_sha256": selected["observation_sha256"],
        "filename": selected["files"][0]["filename"],
        **changes,
    }


def test_three_sources_rank_workload_fit_before_popularity_and_reuse_the_selected_snapshot(sources):
    with TestClient(app) as api:
        search = searched(api)
        pending = queued(api, search)
        assert not sources["calls"]  # HTTP only enqueues.
        work()
        run = api.get("/api/runs/" + pending["id"]).json()
        assert run["status"] == "succeeded", run
        report = run["metadata"]["source_inspection"]
        assert len(sources["calls"]) == 3 and len(report["items"]) == 3
        assert report["items"][0]["repository"] == "publisher/usable"
        assert report["items"][0]["suitability"] == "fits"
        assert report["items"][0]["busy_now"] is True
        assert report["items"][-1]["suitability"] == "does_not_fit"
        assert report["no_weights_downloaded"]
        count = len(sources["calls"])
        request = plan_request(run)
        response = api.post("/api/model-hub/plans", json=request)
        assert response.status_code == 202, response.text
        work()
        planned = api.get("/api/runs/" + response.json()["id"]).json()
        assert planned["status"] == "succeeded", planned
        assert len(sources["calls"]) == count  # No moving-branch resolution on selection.
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelFile))) and not list(db.scalars(select(ModelDefinition)))


def test_partial_access_failure_remains_visible_and_cannot_be_recommended(sources):
    sources["failed"].add("publisher/usable")
    with TestClient(app) as api:
        report = compared(api)["metadata"]["source_inspection"]
    assert report["items"][0]["repository"] == "publisher/also-usable"
    failed = report["items"][-1]
    assert failed["suitability"] == "unavailable" and "access" in failed["summary"]
    assert "observation" not in failed


def test_public_metadata_does_not_make_gated_weights_recommended():
    from test_model_variant_advice import assess

    observation = language_source()
    assess(observation)
    observation["gated"] = True
    score, selected = suitability(observation, set(), 32768)
    assert selected["suitability"] == "access_required" and score[0] == 0
    assert "Publisher access" in selected["summary"]


@pytest.mark.parametrize("missing", ["hardware", "storage"])
def test_unknown_resources_never_recommend_a_model(sources, missing):
    sources[missing] = {} if missing == "hardware" else None
    with TestClient(app) as api:
        report = compared(api)["metadata"]["source_inspection"]
    assert not any(item["suitability"] == "fits" for item in report["items"])


@pytest.mark.parametrize("change", ["parent", "nested", "hash"])
def test_nested_source_plan_requires_both_unchanged_envelope_and_observation(sources, change):
    with TestClient(app) as api:
        run = compared(api)
        request = plan_request(run)
        with control_session_factory()() as db:
            stored = db.get(Run, run["id"])
            report = copy.deepcopy(stored.metadata_json["source_inspection"])
            if change == "parent":
                report["query"] = "tampered"
            elif change == "nested":
                report["items"][0]["observation"]["files"][0]["size_bytes"] += 1
                report["observation_sha256"] = fingerprint(
                    {k: v for k, v in report.items() if k != "observation_sha256"}
                )
            else:
                request["observation_sha256"] = "f" * 64
            stored.metadata_json = {**stored.metadata_json, "source_inspection": report}
            db.commit()
        assert api.post("/api/model-hub/plans", json=request).status_code == 409


def test_stop_before_or_during_comparison_publishes_no_partial_authority(sources):
    with TestClient(app) as api:
        pending = queued(api, searched(api))
        api.post("/api/runs/" + pending["id"] + "/cancel")
        work()
        assert not sources["calls"]
        pending = queued(api, searched(api))
        sources["stop"] = lambda: api.post("/api/runs/" + pending["id"] + "/cancel")
        work()
        run = api.get("/api/runs/" + pending["id"]).json()
        assert run["status"] == "canceled" and "source_inspection" not in run["metadata"]


def test_comparisons_and_nested_source_authority_remain_account_private(accounts, sources):
    owner, alice, bob = accounts
    run = compared(owner)
    assert alice.get("/api/runs/" + run["id"]).status_code == 404
    assert bob.get("/api/runs/" + run["id"]).status_code == 404
    assert alice.post("/api/model-hub/plans", json=plan_request(run)).status_code == 403
