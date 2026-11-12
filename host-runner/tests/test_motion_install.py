"""Fresh setup uses the same typed API and preserves ownership on Stop/recovery."""

import copy
from uuid import uuid4

import pytest
from ai_station_runner import motion_install as install
from ai_station_runner import motion_setup as native
from ai_station_runner.motion_image import recipe as renderer_recipe
from ai_station_runner.runtime_install import atomic_json, directory, load_json
from test_motion_setup import activation as activation
from test_motion_setup import request


class Manager:
    def __init__(self):
        self.processes, self.starts, self.cancels = {}, [], []
        self.lose_ack = False

    def start(self, **value):
        self.starts.append(value)
        self.processes[value["run_id"]] = {
            "alive": True,
            "executor": value["executor"],
            "exit_code": None,
            "completion_pending": False,
        }
        if self.lose_ack:
            self.lose_ack = False
            raise OSError("Synthetic lost launch response")

    def inspect(self, identity, **kwargs):
        return copy.deepcopy(self.processes[str(identity)])

    def cancel(self, identity):
        self.cancels.append(str(identity))
        self.processes[str(identity)].update(alive=False, exit_code=130)


@pytest.fixture
def fresh(activation, monkeypatch):
    a = activation
    a.state["present"] = False
    manager = Manager()
    monkeypatch.setattr(native, "FRESH_QUALIFIED", True)
    monkeypatch.setattr(install, "manager", lambda: manager)
    monkeypatch.setattr(install, "scope_prefix", lambda *_: ["synthetic-owned-scope"])
    monkeypatch.setattr(
        install,
        "prerequisites",
        lambda: {"socket": "/fixture.sock", "id": "fixture-daemon", "data_root": str(a.root)},
    )
    state = {"cleanup_uncertain": False, "cleanups": []}

    def cleanup(identity, saved):
        state["cleanups"].append(str(identity))
        if state["cleanup_uncertain"]:
            raise ValueError("Synthetic uncertain cleanup")
        return True

    monkeypatch.setattr(install.job, "cleanup", cleanup)
    monkeypatch.setattr(
        install.job,
        "image_observation",
        lambda *_: {
            "image_id": a.state["image"]["Id"],
            "recipe_sha256": renderer_recipe(),
            "connection": a.state["connection"],
        },
    )
    return a, manager, state


def start(fresh):
    a, manager, _ = fresh
    body = request()
    reply = a.client.post("/v1/setup/motion/prepare", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["alive"] and reply.json()["status"] == "running"
    assert len(manager.starts) == 1
    return body


def finish(fresh, body, *, lost_exit=False):
    a, manager, _ = fresh
    identity = body["run_id"]
    a.state["present"] = True
    manager.processes[identity].update(alive=False, exit_code=None if lost_exit else 0)
    saved = native.record(identity)
    atomic_json(
        directory(identity),
        "motion-install-result.json",
        {"request_hash": saved["request_hash"], "image_id": a.state["image"]["Id"]},
    )


def test_catalog_admits_fresh_cpu_setup_without_claiming_ready(fresh):
    a, _, _ = fresh
    catalog = a.client.get("/v1/setup/motion").json()
    assert catalog["installation_available"] and not catalog["usable_image"]
    assert catalog["recipe"]["preparation_mode"] == "owned_containers"
    assert catalog["recipe"]["preparation_ram_mib"] == 2304
    assert catalog["recipe"]["download_size_known"] is False


def test_fresh_setup_is_single_launch_and_adopts_ready_after_lost_exit(fresh):
    a, manager, state = fresh
    body = start(fresh)
    again = a.client.post("/v1/setup/motion/prepare", json=body)
    assert again.status_code == 200 and len(manager.starts) == 1
    finish(fresh, body, lost_exit=True)
    result = a.client.get("/v1/setup/motion/" + body["run_id"])
    assert result.status_code == 200 and result.json()["status"] == "succeeded"
    selected = load_json(a.root / "runtime/motion/selection.json")
    assert selected["image_id"] == a.state["image"]["Id"]
    assert selected["activation_request_hash"] == native.record(body["run_id"])["request_hash"]
    assert state["cleanups"]
    assert a.client.get("/v1/setup/motion").json()["usable_image"]


def test_lost_launch_ack_reobserves_without_starting_another_helper(fresh):
    a, manager, _ = fresh
    manager.lose_ack = True
    body = request()
    assert a.client.post("/v1/setup/motion/prepare", json=body).status_code == 200
    result = a.client.post("/v1/setup/motion/prepare", json=body)
    assert result.status_code == 200 and result.json()["alive"]
    assert len(manager.starts) == 1


def test_active_installation_blocks_another_identity(fresh):
    a, manager, _ = fresh
    start(fresh)
    assert a.client.post("/v1/setup/motion/prepare", json=request()).status_code == 409
    assert len(manager.starts) == 1


def test_uncertain_cleanup_keeps_preparation_unready_then_recovers_same_identity(fresh):
    a, manager, state = fresh
    body = start(fresh)
    finish(fresh, body)
    state["cleanup_uncertain"] = True
    result = a.client.get("/v1/setup/motion/" + body["run_id"]).json()
    assert result["requires_inspection"] and not result["alive"]
    assert not (a.root / "runtime/motion/selection.json").exists()
    state["cleanup_uncertain"] = False
    assert a.client.get("/v1/setup/motion/" + body["run_id"]).json()["status"] == "succeeded"
    assert len(manager.starts) == 1


def test_stop_signals_only_its_helper_and_never_publishes_selection(fresh):
    a, manager, _ = fresh
    body = start(fresh)
    reply = a.client.post(
        "/v1/setup/motion/" + body["run_id"] + "/cancel",
        json={"profile": native.PROFILE, "permissions": body["permissions"]},
    )
    assert reply.status_code == 200 and reply.json()["status"] == "canceled", reply.text
    assert manager.cancels == [body["run_id"]]
    assert not (a.root / "runtime/motion/selection.json").exists()
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "canceled"
    assert len(manager.starts) == 1


def test_late_stop_retains_successful_shared_image(fresh):
    a, manager, _ = fresh
    body = start(fresh)
    finish(fresh, body)
    assert a.client.get("/v1/setup/motion/" + body["run_id"]).json()["status"] == "succeeded"
    path = a.root / "runtime/motion/selection.json"
    before = path.read_bytes()
    reply = a.client.post(
        "/v1/setup/motion/" + body["run_id"] + "/cancel",
        json={"profile": native.PROFILE, "permissions": body["permissions"]},
    )
    assert reply.json()["status"] == "canceled"
    assert path.read_bytes() == before
    assert a.client.get("/v1/setup/motion").json()["usable_image"]


def test_prior_success_cannot_overwrite_a_later_manual_selection(fresh):
    a, _, _ = fresh
    body = start(fresh)
    finish(fresh, body)
    assert a.client.get("/v1/setup/motion/" + body["run_id"]).json()["status"] == "succeeded"
    path = a.root / "runtime/motion/selection.json"
    new = {"protocol": 1, "activation_request_hash": str(uuid4())}
    atomic_json(path.parent, path.name, new)
    assert a.client.get("/v1/setup/motion/" + body["run_id"]).json()["requires_inspection"]
    assert load_json(path) == new


def test_pre_dispatch_stop_fences_a_late_prepare(fresh):
    a, manager, _ = fresh
    body = request()
    stopped = a.client.post(
        "/v1/setup/motion/" + body["run_id"] + "/cancel",
        json={"profile": native.PROFILE, "permissions": body["permissions"]},
    )
    assert stopped.status_code == 200
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "canceled"
    assert not manager.starts


def test_no_fresh_installation_when_explicit_engine_is_configured(fresh, monkeypatch):
    from ai_station_runner.config import clear_settings_cache

    a, manager, _ = fresh
    monkeypatch.setenv("AI_STATION_MOTION_IMAGE", "ai-station-motion:explicit-missing")
    clear_settings_cache()
    assert not a.client.get("/v1/setup/motion").json()["installation_available"]
    assert a.client.post("/v1/setup/motion/prepare", json=request()).status_code == 409
    assert not manager.starts


def test_fixed_permission_and_manifest_gate_precedes_launch(fresh):
    a, manager, _ = fresh
    body = request()
    for extra in [
        {"permissions": ["network_read"]},
        {"manifest_sha256": "0" * 64},
        {"image": "unreviewed:latest"},
        {"command": ["sh", "-c", "id"]},
    ]:
        assert a.client.post("/v1/setup/motion/prepare", json={**body, **extra}).status_code in {
            403,
            409,
            422,
        }
    assert not manager.starts


@pytest.mark.parametrize("visible", [False, True])
def test_lost_commit_reply_is_inspected_without_repeating_commit_or_launch(fresh, monkeypatch, visible):
    from contextlib import nullcontext

    import httpx

    a, manager, _ = fresh
    body = start(fresh)
    identity = body["run_id"]
    manager.processes[identity].update(alive=False, exit_code=None)
    saved = native.record(identity)
    atomic_json(
        directory(identity), "motion-commit.json", {"request_hash": saved["request_hash"], "started": True}
    )

    class Committed:
        def get(self, path, **kwargs):
            if path == "/info":
                value = {"ID": "fixture-daemon"}
            else:
                assert path == "/images/json"
                assert (
                    saved["request_hash"] in kwargs["params"]["filters"]
                    and identity in kwargs["params"]["filters"]
                )
                value = [{"Id": a.state["image"]["Id"]}] if visible else []
            return httpx.Response(200, json=value, request=httpx.Request("GET", "http://docker"))

    monkeypatch.setattr(install, "client", lambda *_: nullcontext(Committed()))
    result = a.client.get("/v1/setup/motion/" + identity).json()
    assert result["status"] == ("succeeded" if visible else "interrupted")
    assert result["requires_inspection"] is (not visible)
    assert len(manager.starts) == 1
