"""Actual typed HTTP boundaries over fake Docker and disposable model objects."""

from uuid import uuid4

import pytest
from ai_station_runner import app as host
from ai_station_runner import managed_image_job as job
from ai_station_runner.config import clear_settings_cache
from fastapi.testclient import TestClient
from test_managed_image_job import setup as setup


@pytest.fixture
def client(setup):
    host.reset_manager()
    with TestClient(host.app) as client:
        yield client
    host.reset_manager()


def test_generic_inspection_and_stop_delegate_to_exact_container_journal(setup, client):
    _, _, state, body = setup
    reply = client.post("/v1/runs/managed-image", json=body.model_dump(mode="json"))
    assert reply.status_code == 200 and reply.json()["alive"]
    identity = str(body.run_id)
    job_record = client.get("/v1/process/" + identity).json()
    assert job_record["executor"] == "photo_pipe" and job_record["execution_target"] == "container"
    assert job_record["stdout"] == "loading\n"
    assert client.get(f"/v1/images/jobs/{identity}?stdout_offset=8&stderr_offset=0").json()["stdout"] == ""
    reply = client.post("/v1/process/cancel", json={"run_id": identity})
    assert reply.status_code == 200 and reply.json()["status"] == "canceled"
    assert state["start_count"] == state["stop_count"] == 1


def test_missing_process_inspection_creates_no_image_storage(setup, client):
    root, _, state, _ = setup
    identity = str(uuid4())
    for path in ("/v1/process/", "/v1/images/jobs/"):
        assert client.get(path + identity).status_code == 404
    assert client.post("/v1/process/cancel", json={"run_id": identity}).status_code == 404
    assert not (root / "runtime/image-jobs").exists()
    assert not state["calls"]


def test_stop_before_dispatch_fences_a_late_http_start_even_after_qualification_changes(
    setup, client, monkeypatch
):
    _, _, state, body = setup
    identity = str(body.run_id)
    reply = client.post(f"/v1/images/jobs/{identity}/cancel", json={"permissions": sorted(job.PERMISSIONS)})
    assert reply.status_code == 200 and reply.json()["status"] == "canceled"
    monkeypatch.setattr(job, "QUALIFIED", False)
    late = client.post("/v1/runs/managed-image", json=body.model_dump(mode="json"))
    assert late.status_code == 200 and late.json()["status"] == "canceled"
    assert not state["calls"]
    assert client.get("/v1/process/" + identity).json()["status"] == "canceled"


def test_unqualified_http_start_never_calls_docker(setup, client, monkeypatch):
    _, _, state, body = setup
    monkeypatch.setattr(job, "QUALIFIED", False)
    assert client.post("/v1/runs/managed-image", json=body.model_dump(mode="json")).status_code == 409
    assert not state["calls"]


def test_withdrawing_qualification_cannot_strand_existing_owned_jobs(setup, client, monkeypatch):
    _, _, state, body = setup
    assert client.post("/v1/runs/managed-image", json=body.model_dump(mode="json")).status_code == 200
    monkeypatch.setattr(job, "QUALIFIED", False)
    assert client.get(f"/v1/images/jobs/{body.run_id}").json()["alive"]
    stopped = client.post(
        f"/v1/images/jobs/{body.run_id}/cancel", json={"permissions": sorted(job.PERMISSIONS)}
    )
    assert stopped.status_code == 200 and stopped.json()["status"] == "canceled"
    assert state["start_count"] == state["stop_count"] == 1


def test_partial_explicit_photo_settings_prevent_managed_fallback(setup, client, monkeypatch):
    _, _, state, _ = setup
    monkeypatch.setenv("AI_STATION_PHOTO_PYTHON", "/missing-explicit-environment")
    monkeypatch.setenv("AI_STATION_PHOTO_SCRIPT", "")
    clear_settings_cache()
    monkeypatch.setattr(host, "collect", lambda _: {"gpus": []})
    reply = client.get("/v1/photo/capabilities")
    assert reply.status_code == 200
    assert reply.json()["configuration_source"] == "configured" and not reply.json()["available"]
    assert reply.json()["modes"] == ["t2i", "img2img", "recompose", "upscale"]
    assert "managed_image" not in reply.json() and not state["calls"]


@pytest.mark.parametrize(
    "extra", [{"command": "sh"}, {"image": "unreviewed"}, {"output_relative": "/tmp/owned"}]
)
def test_start_rejects_caller_shell_image_and_output_paths(setup, client, extra):
    _, _, state, body = setup
    payload = {**body.model_dump(mode="json"), **extra}
    assert client.post("/v1/runs/managed-image", json=payload).status_code == 422
    assert not state["calls"]


def test_cancel_requires_both_permissions_and_valid_uuid(setup, client):
    root, _, state, body = setup
    assert client.post(f"/v1/images/jobs/{body.run_id}/cancel", json={"permissions": []}).status_code == 403
    assert (
        client.post(
            "/v1/images/jobs/not-a-uuid/cancel", json={"permissions": sorted(job.PERMISSIONS)}
        ).status_code
        == 422
    )
    assert not (root / "runtime/image-jobs").exists() and not state["calls"]


def test_generic_probe_rejects_symlink_escape_without_creating_external_storage(setup, client):
    root, _, state, body = setup
    external = root / "external"
    external.mkdir()
    (root / "runtime").mkdir(exist_ok=True)
    (root / "runtime/image-jobs").symlink_to(external, target_is_directory=True)
    assert client.get(f"/v1/process/{body.run_id}").status_code == 409
    assert list(external.iterdir()) == [] and not state["calls"]
