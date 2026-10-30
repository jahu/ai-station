"""Native install contracts with temporary journals, fake Docker and managed processes."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from ai_station_runner import runtime_install as native
from ai_station_runner import runtime_install_job as job
from ai_station_runner import runtime_setup
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.processes import ProcessNotOwned
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    clear_settings_cache()
    monkeypatch.setattr(runtime_setup, "platform_supported", lambda: True)
    frozen = runtime_setup.recipe(runtime_setup.RuntimeSelection(profile="llamacpp-cuda-linux-amd64-v1"))
    state = {
        "inspections": [],
        "image": None,
        "calls": [],
        "processes": {},
        "starts": [],
        "cancels": [],
        "progress": [],
    }
    image = {
        "Os": "linux",
        "Architecture": "amd64",
        "Id": "sha256:" + "b" * 64,
        "RepoDigests": [frozen["image_reference"]],
    }

    def docker(request):
        state["calls"].append((request.method, request.url.path))
        if request.url.path == "/info":
            return httpx.Response(200, json={"ID": "synthetic-daemon"})
        if request.method == "POST":
            assert (
                request.url.params["fromImage"] + "@" + request.url.params["tag"] == frozen["image_reference"]
            )
            assert request.url.params["platform"] == "linux/amd64"
            state["image"] = image
            return httpx.Response(
                200, content=b"\n".join(json.dumps(p).encode() for p in state["progress"]) + b"\n"
            )
        return httpx.Response(200, json=state["image"]) if state["image"] else httpx.Response(404, json={})

    monkeypatch.setattr(
        native,
        "client",
        lambda _: httpx.Client(transport=httpx.MockTransport(docker), base_url="http://docker"),
    )
    monkeypatch.setattr(job, "client", native.client)
    monkeypatch.setattr(
        native,
        "daemon",
        lambda: {
            "socket": "/synthetic/docker.sock",
            "id": "synthetic-daemon",
            "api_version": "1.52",
            "data_root": str(tmp_path),
        },
    )
    monkeypatch.setattr(native.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * 1024**3))

    class Manager:
        def start(self, **values):
            identity = values["run_id"]
            state["starts"].append(values)
            state["processes"][identity] = {
                "executor": values["executor"],
                "alive": True,
                "completion_pending": False,
                "exit_code": None,
                "status": "running",
                "stdout": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
            }
            return state["processes"][identity]

        def inspect(self, identity, **kwargs):
            state["inspections"].append((identity, kwargs))
            if identity not in state["processes"]:
                raise ProcessNotOwned(identity)
            return state["processes"][identity]

        def cancel(self, identity):
            state["cancels"].append(identity)
            state["processes"][identity].update(alive=False, status="canceled", exit_code=-15)
            return state["processes"][identity]

    monkeypatch.setattr(native, "process_manager", Manager)
    application = FastAPI()
    application.include_router(native.router)
    with TestClient(application) as api:
        yield SimpleNamespace(api=api, state=state, frozen=frozen, image=image, root=tmp_path)
    clear_settings_cache()


def request(setup):
    return {
        "profile": setup.frozen["profile"],
        "run_id": str(uuid4()),
        "manifest_sha256": runtime_setup.fingerprint(setup.frozen),
        "deadline_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "permissions": sorted(native.PERMISSIONS),
    }


@pytest.mark.parametrize(
    "change,status",
    [
        ({"permissions": ["manage_models"]}, 403),
        ({"manifest_sha256": "f" * 64}, 409),
        ({"image_reference": "any/image:tag"}, 422),
        ({"command": ["id"]}, 422),
        ({"profile": "unreviewed"}, 422),
        ({"deadline_at": "2026-01-01T00:00:00"}, 422),
    ],
)
def test_unreviewed_requests_never_dispatch(setup, change, status):
    response = setup.api.post("/v1/setup/runtimes/prepare", json={**request(setup), **change})
    assert response.status_code == status, response.text
    assert not setup.state["starts"] and not setup.state["calls"]


def test_cancel_before_dispatch_is_durable_and_wins_over_late_prepare(setup):
    body = request(setup)
    identity = body["run_id"]
    response = setup.api.post(
        "/v1/setup/runtimes/" + identity + "/cancel",
        json={"profile": body["profile"], "permissions": body["permissions"]},
    )
    assert response.status_code == 200 and response.json()["status"] == "canceled"
    assert setup.api.post("/v1/setup/runtimes/prepare", json=body).json()["status"] == "canceled"
    assert not setup.state["starts"] and not setup.state["calls"]


def test_cached_image_is_reconciled_without_a_process_and_missing_image_is_not_ready(setup):
    setup.state["image"] = setup.image
    body = request(setup)
    response = setup.api.post("/v1/setup/runtimes/prepare", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert setup.api.post("/v1/setup/runtimes/prepare", json=body).json()["status"] == "succeeded"
    assert not setup.state["starts"]
    setup.state["image"] = None
    assert setup.api.get("/v1/setup/runtimes/" + body["run_id"]).json()["status"] == "interrupted"


def test_request_replay_keeps_one_owned_process_and_frozen_identity(setup):
    body = request(setup)
    first = setup.api.post("/v1/setup/runtimes/prepare", json=body)
    assert first.status_code == 200, first.text
    replay = setup.api.post("/v1/setup/runtimes/prepare", json=body)
    assert replay.status_code == 200, replay.text
    assert len(setup.state["starts"]) == 1
    started = setup.state["starts"][0]
    assert started["argv"][1:] == ["-m", "ai_station_runner.runtime_install_job", body["run_id"]]
    assert started["executor"] == "runtime_setup" and started["deadline_at"] > datetime.now(UTC).timestamp()
    conflict = setup.api.post(
        "/v1/setup/runtimes/prepare",
        json={**body, "deadline_at": (datetime.now(UTC) + timedelta(minutes=40)).isoformat()},
    )
    assert conflict.status_code == 409
    other = setup.api.post("/v1/setup/runtimes/prepare", json=request(setup))
    assert other.status_code == 409, other.text
    assert len(setup.state["starts"]) == 1


def test_owned_transfer_cancellation_does_not_remove_any_image(setup):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    stopped = setup.api.post(
        "/v1/setup/runtimes/" + body["run_id"] + "/cancel",
        json={"profile": body["profile"], "permissions": body["permissions"]},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "canceled" and not stopped.json()["alive"]
    assert setup.state["cancels"] == [body["run_id"]]
    assert all(method == "GET" for method, _ in setup.state["calls"])


def test_uncertain_dispatch_requires_inspection_and_cannot_start_another_pull(setup):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    setup.state["processes"].clear()
    replay = setup.api.post("/v1/setup/runtimes/prepare", json=body)
    assert replay.status_code == 200 and replay.json()["requires_inspection"]
    assert setup.api.post("/v1/setup/runtimes/prepare", json=request(setup)).status_code == 409
    assert len(setup.state["starts"]) == 1


def test_child_streams_real_counters_and_writes_verified_receipt_for_lost_ack_recovery(setup, capsys):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    layer = next(iter(setup.frozen["layers"]))
    setup.state["progress"] = [
        {
            "id": layer[:12],
            "status": "Downloading",
            "progressDetail": {"current": 123, "total": setup.frozen["layers"][layer]},
        },
        {"id": layer[:12], "status": "Download complete"},
    ]
    assert job.run(body["run_id"]) == 0
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert next(v for v in outputs if v["type"] == "runtime.prepare.progress")["received_bytes"] == 123
    record = setup.state["processes"][body["run_id"]]
    record.update(alive=False, status="interrupted", exit_code=None)
    replay = setup.api.post("/v1/setup/runtimes/prepare", json=body)
    assert replay.status_code == 200 and replay.json()["status"] == "succeeded", replay.text
    assert len(setup.state["starts"]) == 1


def test_successful_process_exit_without_a_verified_image_receipt_is_not_success(setup):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    setup.state["processes"][body["run_id"]].update(alive=False, status="exited", exit_code=0)
    result = setup.api.get("/v1/setup/runtimes/" + body["run_id"])
    assert result.status_code == 200 and result.json()["status"] == "failed"


def test_source_tampering_is_rejected_before_opening_a_docker_connection(setup):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    record = native.read(body["run_id"])
    record["recipe"]["image_reference"] = "unreviewed/image:latest"
    native.save(body["run_id"], record)
    setup.state["calls"].clear()
    with pytest.raises(ValueError, match="source identity"):
        job.run(body["run_id"])
    assert not setup.state["calls"]


def test_saved_log_offsets_are_bounded_and_forwarded_to_the_owned_process(setup):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    path = "/v1/setup/runtimes/" + body["run_id"]
    response = setup.api.get(path + "?stdout_offset=17&stderr_offset=24")
    assert response.status_code == 200, response.text
    assert setup.state["inspections"][-1] == (body["run_id"], {"stdout_offset": 17, "stderr_offset": 24})
    assert setup.api.get(path + "?stdout_offset=-1").status_code == 422
    assert setup.api.get(path + "?stderr_offset=99999999999999999999").status_code == 422


def test_runtime_storage_symlink_escape_is_rejected_before_a_docker_operation(setup, tmp_path):
    target = tmp_path / "outside-runtime"
    target.mkdir()
    (setup.root / "runtime").symlink_to(target, target_is_directory=True)
    response = setup.api.post("/v1/setup/runtimes/prepare", json=request(setup))
    assert response.status_code == 409, response.text
    assert not setup.state["calls"] and not setup.state["starts"]


def test_atomic_receipt_does_not_follow_a_preexisting_temporary_symlink(setup):
    body = request(setup)
    setup.api.post("/v1/setup/runtimes/prepare", json=body).raise_for_status()
    victim = setup.root / "keep.txt"
    victim.write_text("Preserve this file")
    (native.directory(body["run_id"]) / "result.tmp").symlink_to(victim)
    assert job.run(body["run_id"]) == 0
    assert victim.read_text() == "Preserve this file"
