"""Native SDK lifecycle uses fake processes and verified synthetic Mach-O bytes."""

import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import native_llama_prepare as native
from ai_station_runner import runtime_install
from ai_station_runner.darwin_llama_environment import NAMESPACE, Environment
from ai_station_runner.processes import ProcessNotOwned
from fastapi import HTTPException
from pydantic import ValidationError
from test_darwin_llama_bundle import fixture as fixture


@pytest.fixture
def setup(fixture, monkeypatch):
    root = fixture["root"]
    profile = "llamacpp-native-darwin-arm64-b12032-v2"
    fixture["frozen"].update(profile=profile, minimum_os=[13, 3, 0])
    settings = SimpleNamespace(host_data_dir=lambda: root, runner_id="native-sdk-unit")
    monkeypatch.setattr(runtime_install, "get_settings", lambda: settings)
    monkeypatch.setattr(native, "get_settings", lambda: settings)
    monkeypatch.setattr(native, "collect", lambda _: {"memory": {"available_mib": 4096}})
    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(native.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(native.platform, "mac_ver", lambda: ("13.3", "", ""))
    state = {"starts": [], "processes": {}, "cancels": [], "lost_ack": False}

    class Manager:
        def start(self, **value):
            state["starts"].append(value)
            state["processes"][value["run_id"]] = {
                "executor": value["executor"],
                "status": "running",
                "alive": True,
                "exit_code": None,
            }
            if state["lost_ack"]:
                raise OSError("Synthetic lost acknowledgement")

        def inspect(self, identity, **kwargs):
            if str(identity) not in state["processes"]:
                raise ProcessNotOwned(identity)
            return dict(state["processes"][str(identity)])

        def cancel(self, identity):
            state["cancels"].append(str(identity))
            state["processes"][str(identity)].update(status="canceled", alive=False, exit_code=-15)

    body = native.Preparation(
        profile=profile,
        run_id=uuid4(),
        permissions=sorted(native.PERMISSIONS),
        manifest_sha256=Environment(profile).fingerprint(fixture["frozen"]),
        deadline_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    return root, Manager(), body, state


def prepared(setup, *, exit_code=0):
    root, _, body, state = setup
    env = Environment(body.profile)
    env.prepare(root, body.run_id)
    state["processes"][str(body.run_id)].update(
        status="exited" if exit_code is not None else "interrupted", alive=False, exit_code=exit_code
    )
    return env


def test_sdk_start_uses_owned_isolated_python_and_lost_ack_is_not_replayed(setup):
    root, manager, body, state = setup
    policy = native.controller(body.profile)
    state["lost_ack"] = True
    with pytest.raises(OSError):
        policy.start(manager, body)
    assert policy.start(manager, body)["status"] == "running"
    assert len(state["starts"]) == 1
    launched = state["starts"][0]
    assert launched["argv"][:4] == [
        sys.executable,
        "-IB",
        "-m",
        "ai_station_runner.native_llama_environment_job",
    ]
    assert launched["cwd"] == root and launched["deadline_at"] == body.deadline_at.timestamp()
    assert "PYTHONPATH" not in launched["env"] and not launched["argv"][0].endswith("systemd-run")


def test_pre_dispatch_stop_is_durable_and_blocks_a_delayed_start(setup):
    _, manager, body, state = setup
    policy = native.controller(body.profile)
    assert policy.cancel(manager, body.run_id, body)["status"] == "canceled"
    assert policy.start(manager, body)["status"] == "canceled"
    assert not state["starts"]


def test_cancel_after_sdk_completion_still_prevents_activation(setup):
    _, manager, body, state = setup
    policy = native.controller(body.profile)
    policy.start(manager, body)
    prepared(setup)
    policy.cancel(manager, body.run_id, body)
    with pytest.raises(HTTPException, match="completed native"):
        policy.adopt(manager, body.run_id, body)
    assert state["cancels"] == [str(body.run_id)]


def test_restart_unknown_exit_uses_exact_ready_bundle_without_reexecution(setup):
    root, manager, body, state = setup
    policy = native.controller(body.profile)
    policy.start(manager, body)
    env = prepared(setup, exit_code=None)
    result = policy.inspection(manager, body.run_id)
    assert (
        result["status"] == "succeeded"
        and result["environment_prepared"]
        and not result["requires_inspection"]
    )
    selected = policy.adopt(manager, body.run_id, body)
    observed = env.observation(body.run_id)
    assert (
        env.resolve_id(root, env.fingerprint(observed))["bundle"]["manifest_sha256"] == body.manifest_sha256
    )
    assert len(state["starts"]) == 1 and selected["operation_id"] == str(body.run_id)
    catalog = native.Policy(body.profile).catalog()
    assert catalog["sdk_prepared"] and "operation_id" not in catalog["environment"]
    assert str(body.run_id) not in json.dumps(catalog)


def test_tampered_sdk_cannot_be_recovered_or_adopted(setup):
    root, manager, body, state = setup
    policy = native.controller(body.profile)
    policy.start(manager, body)
    env = prepared(setup, exit_code=None)
    engine = root / "runtime/native-llama" / body.manifest_sha256 / str(body.run_id) / "engine/llama-server"
    engine.chmod(0o755)
    engine.write_bytes(b"changed owned bytes")
    result = policy.inspection(manager, body.run_id)
    assert result["requires_inspection"] and result["status"] == "interrupted"
    with pytest.raises(HTTPException):
        policy.adopt(manager, body.run_id, body)
    with pytest.raises(ValueError):
        env.resolve(root, env.observation(body.run_id))
    assert len(state["starts"]) == 1


def test_changed_private_identity_map_is_not_reported_as_ready(setup):
    root, manager, body, _ = setup
    policy = native.controller(body.profile)
    policy.start(manager, body)
    env = prepared(setup)
    policy.adopt(manager, body.run_id, body)
    identity = env.fingerprint(env.observation(body.run_id))
    mapping = root / "runtime" / NAMESPACE / "identities" / (identity + ".json")
    mapping.unlink()
    assert native.Policy(body.profile).catalog()["environment"] is None


def test_missing_permissions_and_immutable_changed_request_never_start_another_process(setup):
    _, manager, body, state = setup
    policy = native.controller(body.profile)
    with pytest.raises(HTTPException) as denied:
        policy.start(manager, body.model_copy(update={"permissions": []}))
    assert denied.value.status_code == 403 and not state["starts"]
    policy.start(manager, body)
    with pytest.raises(HTTPException) as changed:
        policy.start(manager, body.model_copy(update={"manifest_sha256": "0" * 64}))
    assert changed.value.status_code == 409 and len(state["starts"]) == 1


def test_foreign_executor_is_not_canceled(setup):
    _, manager, body, state = setup
    policy = native.controller(body.profile)
    policy.start(manager, body)
    state["processes"][str(body.run_id)]["executor"] = "unrelated"
    with pytest.raises(HTTPException, match="another executor"):
        policy.cancel(manager, body.run_id, body)
    assert not state["cancels"]


def test_unsupported_platform_does_not_launch_or_silently_fall_back(setup, monkeypatch):
    _, manager, body, state = setup
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    assert not native.Policy(body.profile).catalog()["installation_available"]
    with pytest.raises(HTTPException):
        native.controller(body.profile).start(manager, body)
    assert not state["starts"]


@pytest.mark.parametrize(
    "field,value", [("command", ["id"]), ("binary", "/tmp/arbitrary"), ("profile", "unreviewed")]
)
def test_unreviewed_request_fields_are_not_an_execution_interface(setup, field, value):
    _, _, body, _ = setup
    with pytest.raises(ValidationError):
        native.Preparation.model_validate({**body.model_dump(), field: value})
