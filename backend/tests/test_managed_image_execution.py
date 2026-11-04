"""Ordinary image API/worker/resource/artifact lifecycle with a fake native bridge."""

import io
from datetime import timedelta

import pytest
from app.api import app
from app.config import get_settings
from app.db import control_session_factory, session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ResourceLock, Run, RunEvent
from app.recovery import recover_stale
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def all_locks(session):
    return set(session.scalars(select(ResourceLock.resource_key).where(ResourceLock.released_at.is_(None))))


@pytest.fixture
def bridge(monkeypatch):
    state = {
        "calls": [],
        "start": None,
        "after_catalog": None,
        "after_start": None,
        "missing": False,
        "fence_error": False,
        "on_inspect": None,
    }
    descriptor = {
        "profile": "qwen-image21-cuda-linux-amd64-v1",
        "manifest_sha256": "a" * 64,
        "gpu_count": 2,
        "eligible_gpu_indices": [7, 9],
        "diffusion_sha256": "b" * 64,
        "diffusion_size_bytes": 123,
    }
    capabilities = {"configuration_source": "managed", "available": True, "managed_image": descriptor}
    terminal = dict(
        runner_id="fake-image-runner",
        pid=12345,
        process_group_id=None,
        executor="photo_pipe",
        execution_target="container",
        alive=False,
        status="exited",
        exit_code=0,
        stdout="",
        stderr="",
        stdout_offset=0,
        stderr_offset=0,
        stdout_more=False,
        stderr_more=False,
    )
    state["terminal"] = terminal

    def request(self, method, path, json=None):
        state["calls"].append((method, path, json))
        if path == "/v1/photo/capabilities":
            if state["after_catalog"]:
                state["after_catalog"]()
            return capabilities
        if path == "/v1/hardware":
            return {"gpus": [{"index": 7}, {"index": 9}], "memory": {"available_mib": 24576}}
        if path == "/v1/runs/managed-image":
            state["start"] = json
            terminal["run_id"] = json["run_id"]
            with session_factory()() as db:
                run = db.get(Run, json["run_id"])
                assert run.metadata_json["dispatch_attempted"]
                expected = {"gpu:7", "ram:" + run.id}
                if json["command"]["mode"] != "upscale":
                    expected.add("gpu:9")
                assert all_locks(db) == expected
                assert run.execution_target == "container"
            root = get_settings().data_dir
            identity = json["run_id"]
            target = root / f"artifacts/{identity[:2]}/{identity[2:4]}/{identity}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            command = json["command"]
            Image.new("RGB", (command["width"], command["height"]), "green").save(target)
            if state["after_start"]:
                state["after_start"]()
            return terminal
        if path.startswith("/v1/images/jobs/") or path.startswith("/v1/process/"):
            if path.endswith("/cancel"):
                if state["fence_error"]:
                    raise RunnerUnavailable("synthetic stop uncertainty")
                terminal.update(status="canceled", exit_code=None)
                return terminal
            if state["missing"]:
                if state["on_inspect"]:
                    state["on_inspect"]()
                raise RunnerError(404, "not yet received")
            return terminal
        raise AssertionError((method, path, json))

    monkeypatch.setattr(RunnerClient, "request", request)
    return state, capabilities


def source(api):
    data = io.BytesIO()
    Image.new("RGB", (512, 768), "blue").save(data, "PNG")
    reply = api.post("/api/images/uploads", files={"file": ("source.png", data.getvalue(), "image/png")})
    assert reply.status_code == 201, reply.text
    return reply.json()


def queue(api, mode="t2i", count=0, **changes):
    parents = [source(api) for _ in range(count)]
    body = {
        "mode": mode,
        "prompt": "A quiet landscape",
        "edit_prompt": "Remove the red cup",
        "width": 512,
        "height": 512,
        "max_side": 512,
        "input_artifact_ids": [item["id"] for item in parents],
        **changes,
    }
    reply = api.post("/api/images/runs", json=body)
    assert reply.status_code == 202, reply.text
    return reply.json(), parents


@pytest.mark.parametrize(
    "mode,count,style",
    [
        ("t2i", 0, "prompt"),
        ("t2i", 0, "pipeline"),
        ("img2img", 1, "instruction"),
        ("img2img", 1, "pipeline"),
        ("recompose", 1, "instruction"),
        ("recompose", 2, "pipeline"),
    ],
)
def test_prepared_images_use_normal_owned_run_and_frozen_sources(bridge, mode, count, style):
    state, _ = bridge
    with TestClient(app) as api:
        run, parents = queue(api, mode, count, prompt_style=style)
        assert state["calls"] == []  # API only enqueues.
        with session_factory()() as db:
            tick(db, "image-worker")
            saved = db.get(Run, run["id"])
            assert saved.status == "succeeded", saved.error_message
            assert active_locks(db) == set()
            assert saved.metadata_json["process_confirmed_gone"]
            assert saved.requested_resources["ram_mib"] == 12288
        payload = state["start"]
        assert payload["gpus"] == [7, 9] and payload["command"]["reference_count"] == count
        expected = "Remove the red cup" if mode == "img2img" else "A quiet landscape"
        if style in {"instruction", "prompt"}:
            assert payload["command"]["prompt"] == expected
        else:
            assert expected in payload["command"]["prompt"] and payload["command"]["prompt"] != expected
        assert payload["command"]["cfg"] == (6.0 if mode != "t2i" else 5.0)
        assert len(payload["references"]) == len(parents)
        artifacts = api.get(f"/api/artifacts?run_id={run['id']}").json()
        assert len(artifacts) == 1
        assert artifacts[0]["parent_artifact_ids"] == [item["id"] for item in parents]
        assert artifacts[0]["metadata"]["managed_image_runtime"]["command"] == payload["command"]
        if mode == "img2img":
            assert (payload["command"]["width"], payload["command"]["height"]) == (352, 512)


def test_candidate_unavailable_fails_before_any_resource_or_dispatch(bridge):
    state, capabilities = bridge
    capabilities["available"] = False
    with TestClient(app) as api:
        run, _ = queue(api)
        with session_factory()() as db:
            tick(db, "image-worker")
            saved = db.get(Run, run["id"])
            assert saved.status == "failed" and "qualified" in saved.error_message
            assert active_locks(db) == set()
        assert state["start"] is None


@pytest.mark.parametrize("missing", ["filesystem_read", "workspace_write"])
def test_missing_permission_is_rejected_before_preflight_or_reading_sources(bridge, missing):
    state, _ = bridge
    with TestClient(app) as api:
        run, _ = queue(api, "img2img", 1, prompt_style="instruction")
        with session_factory()() as db:
            row = db.get(Run, run["id"])
            row.effective_permissions = [
                permission for permission in row.effective_permissions if permission != missing
            ]
            db.commit()
            tick(db, "unpermitted-image-worker")
            assert db.get(Run, run["id"]).status == "failed"
            assert all_locks(db) == set()
        assert state["calls"] == []


def test_stop_during_native_dispatch_never_publishes_result(bridge):
    state, _ = bridge
    with TestClient(app) as api:
        run, _ = queue(api)
        state["after_start"] = lambda: api.post(f"/api/runs/{run['id']}/cancel").raise_for_status()
        with session_factory()() as db:
            tick(db, "image-worker")
            assert db.get(Run, run["id"]).status == "canceled"
            assert active_locks(db) == set()
        assert api.get(f"/api/artifacts?run_id={run['id']}").json() == []
        assert any(path.endswith("/cancel") for _, path, _ in state["calls"])


@pytest.mark.parametrize("fence_error", [False, True])
def test_lost_dispatch_and_missing_journal_require_stop_fence_before_resource_release(bridge, fence_error):
    state, _ = bridge
    with TestClient(app) as api:
        run, _ = queue(api)

        def lose_response():
            raise RunnerUnavailable("synthetic lost start response")

        state["after_start"] = lose_response
        with session_factory()() as db:
            tick(db, "image-worker")
            saved = db.get(Run, run["id"])
            assert saved.status == "preparing" and all_locks(db) == {"gpu:7", "gpu:9", "ram:" + saved.id}
            saved.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
            state.update(missing=True, fence_error=fence_error)
            recover_stale(db)
            db.refresh(saved)
            assert saved.status == ("preparing" if fence_error else "interrupted")
            assert bool(active_locks(db)) is fence_error
        assert sum(path == "/v1/runs/managed-image" for _, path, _ in state["calls"]) == 1


def test_replaced_worker_claim_during_capabilities_read_cannot_dispatch(bridge):
    state, _ = bridge
    with TestClient(app) as api:
        run, _ = queue(api)

        def replace_claim():
            with session_factory()() as db:
                row = db.get(Run, run["id"])
                row.worker_id = "replacement-worker"
                row.claimed_at = utcnow()
                db.commit()

        state["after_catalog"] = replace_claim
        with session_factory()() as db:
            tick(db, "old-worker")
            db.expire_all()
            assert db.get(Run, run["id"]).worker_id == "replacement-worker"
            assert active_locks(db) == set()
        assert state["start"] is None


def test_reference_change_after_queue_is_rejected_before_dispatch(bridge):
    state, _ = bridge
    with TestClient(app) as api:
        run, parents = queue(api, "img2img", 1, prompt_style="instruction")

        def change_source():
            with session_factory()() as db:
                row = db.get(Artifact, parents[0]["id"])
                (get_settings().data_dir / row.relative_path).write_bytes(b"changed source")

        state["after_catalog"] = change_source
        with session_factory()() as db:
            tick(db, "image-worker")
            assert db.get(Run, run["id"]).status == "failed"
            assert active_locks(db) == set()
        assert state["start"] is None


def test_member_image_output_sources_and_events_remain_private(bridge, accounts):
    _, alice, bob = accounts
    run, parents = queue(alice, "img2img", 1, prompt_style="instruction")
    assert bob.get(f"/api/runs/{run['id']}").status_code == 404
    assert bob.get(f"/api/runs/{run['id']}/events").status_code == 404
    with control_session_factory()() as db:
        tick(db, "owned-image-worker")
        assert db.get(Run, run["id"]).status == "succeeded"
        assert all_locks(db) == set()
    artifact = alice.get(f"/api/artifacts?run_id={run['id']}").json()[0]
    for identity in (parents[0]["id"], artifact["id"]):
        assert bob.get(f"/api/artifacts/{identity}/file").status_code == 404
        assert alice.get(f"/api/artifacts/{identity}/file").status_code == 200
    assert bob.post(f"/api/runs/{run['id']}/cancel").status_code == 404


@pytest.mark.parametrize("fence_error", [False, True])
def test_disabled_owner_stops_only_the_owned_container_before_releasing_resources(
    bridge, accounts, fence_error
):
    state, _ = bridge
    owner, alice, _ = accounts
    user_id = alice.get("/api/auth").json()["user"]["id"]
    run, _ = queue(alice)
    state["after_start"] = lambda: owner.patch(
        f"/api/admin/users/{user_id}", json={"enabled": False, "is_admin": False}
    ).raise_for_status()
    state["fence_error"] = fence_error
    with control_session_factory()() as db:
        tick(db, "revoked-image-worker")
        saved = db.get(Run, run["id"], populate_existing=True)
        assert saved.status == ("cancel_requested" if fence_error else "canceled"), [
            (event.event_type, event.payload)
            for event in db.scalars(select(RunEvent).where(RunEvent.run_id == saved.id))
        ]
        assert bool(all_locks(db)) is fence_error
        assert not list(db.scalars(select(Artifact).where(Artifact.run_id == run["id"])))
    assert any(path == f"/v1/images/jobs/{run['id']}/cancel" for _, path, _ in state["calls"])


def test_recovery_does_not_fence_a_lease_renewed_during_missing_journal_inspection(bridge):
    state, _ = bridge
    with TestClient(app) as api:
        run, _ = queue(api)

        def lose_response():
            raise RunnerUnavailable("synthetic lost start response")

        state["after_start"] = lose_response
        with session_factory()() as db:
            tick(db, "image-worker")
            saved = db.get(Run, run["id"])
            saved.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()

            def renew():
                with session_factory()() as other:
                    other.get(Run, saved.id).lease_expires_at = utcnow() + timedelta(minutes=1)
                    other.commit()

            state.update(missing=True, on_inspect=renew)
            assert recover_stale(db) == []
            assert all_locks(db) == {"gpu:7", "gpu:9", "ram:" + saved.id}
        assert not any(path.endswith("/cancel") for _, path, _ in state["calls"])


def test_retry_renews_native_deadline_but_retains_the_frozen_effective_prompt_and_seed(bridge, monkeypatch):
    from app import managed_image_execution

    state, _ = bridge
    seeds = iter([1234, 5678])
    monkeypatch.setattr(managed_image_execution.secrets, "randbits", lambda _: next(seeds))
    with TestClient(app) as api:
        run, _ = queue(api, prompt_style="prompt")
        state["terminal"]["exit_code"] = 3
        with session_factory()() as db:
            tick(db, "first-image-worker")
            original = db.get(Run, run["id"])
            assert original.status == "failed"
            assert original.parameters["managed_image_runtime"]["command"]["seed"] == 1234
            original.parameters = {
                **original.parameters,
                "managed_image_native_deadline_at": (utcnow() - timedelta(days=1)).isoformat(),
            }
            db.commit()
        reply = api.post(f"/api/images/runs/{run['id']}/retry")
        assert reply.status_code == 202, reply.text
        retry = reply.json()
        state["terminal"]["exit_code"] = 0
        with session_factory()() as db:
            tick(db, "retry-image-worker")
            saved = db.get(Run, retry["id"])
            assert saved.status == "succeeded", saved.error_message
            assert saved.task_id == run["task_id"] and saved.parent_run_id == run["id"]
            assert saved.parameters["managed_image_runtime"]["command"]["seed"] == 1234
            assert state["start"]["command"]["prompt"] == "A quiet landscape"
            assert saved.parameters["managed_image_native_deadline_at"] > utcnow().isoformat()
        another, _ = queue(api, prompt_style="prompt")
        with session_factory()() as db:
            tick(db, "another-image-worker")
            assert db.get(Run, another["id"]).status == "succeeded"
        assert state["start"]["command"]["seed"] == 5678


def test_upscale_uses_one_gpu_and_exact_source_geometry_without_generation_controls(bridge):
    state, _ = bridge
    with TestClient(app) as api:
        run, parents = queue(api, "upscale", 1)
        with session_factory()() as db:
            tick(db, "upscale-worker")
            saved = db.get(Run, run["id"])
            assert saved.status == "succeeded", saved.error_message
            assert all_locks(db) == set()
        assert state["start"]["gpus"] == [7]
        command = state["start"]["command"]
        assert command == dict(
            mode="upscale",
            prompt="",
            reference_count=1,
            width=2048,
            height=3072,
            steps=None,
            cfg=None,
            seed=None,
        )
        artifact = api.get(f"/api/artifacts?run_id={run['id']}").json()[0]
        assert artifact["parent_artifact_ids"] == [parents[0]["id"]]
        assert (artifact["metadata"]["width"], artifact["metadata"]["height"]) == (2048, 3072)


def test_image_readiness_is_shared_metadata_without_dispatch_or_private_inputs(bridge, accounts):
    state, _ = bridge
    _, alice, bob = accounts
    for browser in (alice, bob):
        reply = browser.get("/api/images/capabilities")
        assert reply.status_code == 200 and reply.json()["available"] is True
        assert set(reply.json()) == {"configuration_source", "available", "managed_image"}
    assert state["start"] is None


def test_image_readiness_reports_unknown_runner_without_enqueuing_a_job(monkeypatch):
    def missing(*args, **kwargs):
        raise RunnerUnavailable("fixture unavailable")

    monkeypatch.setattr(RunnerClient, "request", missing)
    with TestClient(app) as api:
        reply = api.get("/api/images/capabilities")
        assert reply.status_code == 200
        assert reply.json()["available"] is False and reply.json()["status"] == "unknown"
        assert api.get("/api/runs").json() == []


def test_large_generated_library_image_can_be_edited_without_relaxing_upload_or_vision_limits(
    bridge, tmp_path
):
    import random

    from app.artifacts import register_file
    from app.vision_inputs import LIMIT, snapshot, verify

    state, _ = bridge
    path = tmp_path / "large-generated.png"
    image = Image.frombytes("RGB", (3072, 3072), random.Random(42).randbytes(3072 * 3072 * 3))
    image.save(path)
    path.chmod(0o600)
    assert path.stat().st_size > LIMIT
    with session_factory()() as db:
        source = register_file(
            db,
            source=path,
            artifact_type="image",
            mime_type="image/png",
            original_filename="large-generated.png",
            run_id=None,
        )
        identity = source.id
        db.commit()
        with pytest.raises(ValueError):
            verify(db, [snapshot(source)], read_bytes=True)
    with TestClient(app) as api:
        reply = api.post(
            "/api/images/runs",
            json={
                "mode": "img2img",
                "edit_prompt": "Remove the red cup",
                "prompt_style": "instruction",
                "max_side": 512,
                "input_artifact_ids": [identity],
            },
        )
        assert reply.status_code == 202, reply.text
        with session_factory()() as db:
            tick(db, "large-image-worker")
            run = db.get(Run, reply.json()["id"])
            assert run.status == "succeeded", run.error_message
        assert state["start"]["references"][0]["size_bytes"] > LIMIT
        assert state["start"]["command"]["width"] == state["start"]["command"]["height"] == 512
