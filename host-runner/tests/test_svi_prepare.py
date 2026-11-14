"""Typed native lifecycle with fake processes; no SDK, model, pip or GPU."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import runtime_install, svi_environment, svi_prepare
from ai_station_runner.processes import ProcessNotOwned
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = SimpleNamespace(host_data_dir=lambda: tmp_path)
    monkeypatch.setattr(runtime_install, "get_settings", lambda: settings)
    monkeypatch.setattr(svi_prepare, "get_settings", lambda: settings)
    monkeypatch.setattr(svi_environment, "QUALIFIED", True)
    monkeypatch.setattr(svi_environment, "remember", lambda root, observation: None)
    frozen = svi_environment.recipe()
    digest = svi_environment.fingerprint(frozen)
    monkeypatch.setattr(
        svi_prepare, "catalog", lambda: {"installation_available": True, "manifest_sha256": digest}
    )
    monkeypatch.setattr(svi_prepare, "scope_prefix", lambda identity, maximum: ["fixed-scope", str(maximum)])
    state = {"starts": [], "cancels": [], "processes": {}, "lost_ack": False}

    class Manager:
        def start(self, **values):
            state["starts"].append(values)
            state["processes"][values["run_id"]] = {
                "executor": values["executor"],
                "status": "running",
                "alive": True,
                "exit_code": None,
            }
            if state["lost_ack"]:
                raise OSError("Synthetic lost start acknowledgement")

        def inspect(self, identity, **offsets):
            if identity not in state["processes"]:
                raise ProcessNotOwned(identity)
            return dict(state["processes"][identity])

        def cancel(self, identity):
            state["cancels"].append(identity)
            state["processes"][identity].update(alive=False, status="canceled", exit_code=-15)

    body = svi_prepare.Preparation(
        profile=svi_environment.PROFILE,
        run_id=uuid4(),
        manifest_sha256=digest,
        permissions=sorted(svi_prepare.PERMISSIONS),
        deadline_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    return tmp_path, Manager(), body, state


def complete(setup, **changes):
    root, _, body, state = setup
    identity = str(body.run_id)
    state["processes"][identity].update(alive=False, status="exited", exit_code=0)
    relative = f"runtime/svi-environments/{body.manifest_sha256}/{identity}"
    folder = svi_environment.directory(
        root / "runtime", f"svi-environments/{body.manifest_sha256}/{identity}"
    )
    receipt = {
        "profile": body.profile,
        "manifest_sha256": body.manifest_sha256,
        "operation_id": identity,
        "relative_path": relative,
        "environment_prepared": True,
        **changes,
    }
    (folder / "ready.json").write_text(json.dumps(receipt))
    (folder / "ready.json").chmod(0o600)
    return folder


def test_lost_ack_and_repeat_start_never_duplicate_native_install(setup):
    root, manager, body, state = setup
    state["lost_ack"] = True
    with pytest.raises(OSError):
        svi_prepare.start(manager, body)
    result = svi_prepare.start(manager, body)
    assert result["status"] == "running" and len(state["starts"]) == 1
    command = state["starts"][0]
    assert command["argv"][:2] == ["fixed-scope", "4096"]
    assert command["argv"][-2] == "ai_station_runner.svi_environment_job"
    assert command["executor"] == "svi_environment_setup" and command["cwd"] == root
    assert command["deadline_at"] == body.deadline_at.timestamp()
    assert not {"PIP_INDEX_URL", "HTTPS_PROXY", "LD_PRELOAD"} & command["env"].keys()


def test_pre_dispatch_stop_is_durable_and_prevents_late_start(setup):
    _, manager, body, state = setup
    result = svi_prepare.cancel(manager, body.run_id, body)
    assert result["status"] == "canceled" and not result["alive"]
    assert svi_prepare.start(manager, body)["status"] == "canceled"
    assert not state["starts"] and not state["cancels"]


def test_deadline_is_immutable_and_a_late_repeat_only_inspects(setup, monkeypatch):
    _, manager, body, state = setup
    svi_prepare.start(manager, body)
    changed = body.model_copy(update={"deadline_at": body.deadline_at + timedelta(minutes=1)})
    with pytest.raises(HTTPException) as exc:
        svi_prepare.start(manager, changed)
    assert exc.value.status_code == 409
    monkeypatch.setattr(svi_prepare, "catalog", lambda: {"installation_available": False})
    monkeypatch.setattr(__import__("time"), "time", lambda: body.deadline_at.timestamp() + 1)
    assert svi_prepare.start(manager, body)["status"] == "running"
    assert len(state["starts"]) == 1


def test_complete_preparation_is_not_active_until_explicit_adoption(setup):
    root, manager, body, _ = setup
    svi_prepare.start(manager, body)
    folder = complete(setup)
    ready = svi_prepare.inspection(manager, body.run_id)
    assert ready["status"] == "succeeded" and ready["environment_prepared"]
    assert not (root / "runtime/svi-environments/active.json").exists()
    result = svi_prepare.adopt(manager, body.run_id, body)
    selected = json.loads((root / "runtime/svi-environments/active.json").read_text())
    assert selected["operation_id"] == str(body.run_id)
    assert result["environment_prepared"] and not result["svi_inference_tested_now"]
    assert (folder / "ready.json").is_file()


@pytest.mark.parametrize(
    "change",
    [
        {"operation_id": "wrong"},
        {"manifest_sha256": "0" * 64},
        {"environment_prepared": False},
        {"relative_path": "../escape"},
        {"profile": "other"},
    ],
)
def test_successful_process_without_exact_readiness_cannot_activate(setup, change):
    root, manager, body, _ = setup
    svi_prepare.start(manager, body)
    complete(setup, **change)
    assert svi_prepare.inspection(manager, body.run_id)["requires_inspection"]
    with pytest.raises(HTTPException) as exc:
        svi_prepare.adopt(manager, body.run_id, body)
    assert exc.value.status_code == 409 and not (root / "runtime/svi-environments/active.json").exists()


def test_stop_serializes_against_adoption_even_if_ready_file_exists(setup):
    root, manager, body, state = setup
    svi_prepare.start(manager, body)
    complete(setup)
    assert svi_prepare.cancel(manager, body.run_id, body)["status"] == "canceled"
    with pytest.raises(HTTPException):
        svi_prepare.adopt(manager, body.run_id, body)
    assert not (root / "runtime/svi-environments/active.json").exists()
    assert state["cancels"] == [str(body.run_id)]


def test_failed_private_identity_publication_preserves_previous_active_environment(setup, monkeypatch):
    root, manager, body, _ = setup
    svi_prepare.start(manager, body)
    complete(setup)
    folder = svi_environment.directory(root / "runtime", "svi-environments")
    previous = {
        "profile": body.profile,
        "operation_id": str(uuid4()),
        "manifest_sha256": body.manifest_sha256,
    }
    runtime_install.atomic_json(folder, "active.json", previous)

    def fail(root, observation):
        assert observation["operation_id"] == str(body.run_id)
        raise OSError("Synthetic private identity publication failure")

    monkeypatch.setattr(svi_environment, "remember", fail)
    with pytest.raises(OSError, match="identity publication"):
        svi_prepare.adopt(manager, body.run_id, body)
    assert svi_environment.read_json(folder / "active.json") == previous


def test_journal_without_confirmed_process_requires_inspection_not_reexecution(setup):
    _, manager, body, state = setup
    svi_prepare.start(manager, body)
    state["processes"].clear()
    result = svi_prepare.start(manager, body)
    assert result["status"] == "interrupted" and result["requires_inspection"]
    assert len(state["starts"]) == 1


def test_cancel_never_signals_another_executor(setup):
    _, manager, body, state = setup
    svi_prepare.start(manager, body)
    state["processes"][str(body.run_id)]["executor"] = "unrelated"
    with pytest.raises(HTTPException) as exc:
        svi_prepare.cancel(manager, body.run_id, body)
    assert exc.value.status_code == 409 and not state["cancels"]


@pytest.mark.parametrize("stage", ["start", "cancel", "adopt"])
def test_model_network_workspace_authority_required(setup, stage):
    _, manager, body, state = setup
    body = body.model_copy(update={"permissions": ["manage_models"]})
    with pytest.raises(HTTPException) as exc:
        if stage == "start":
            svi_prepare.start(manager, body)
        else:
            getattr(svi_prepare, stage)(manager, body.run_id, body)
    assert exc.value.status_code == 403 and not state["starts"] and not state["cancels"]


def test_unqualified_installer_stays_unavailable(setup, monkeypatch):
    _, manager, body, state = setup
    monkeypatch.setattr(
        svi_prepare,
        "catalog",
        lambda: {"installation_available": False, "installation_notice": "Not qualified"},
    )
    with pytest.raises(HTTPException):
        svi_prepare.start(manager, body)
    assert not state["starts"]


@pytest.mark.parametrize("hours", [-1, 5])
def test_invalid_deadline_cannot_start_a_process(setup, hours):
    _, manager, body, state = setup
    body = body.model_copy(update={"deadline_at": datetime.now(UTC) + timedelta(hours=hours)})
    with pytest.raises(HTTPException) as exc:
        svi_prepare.start(manager, body)
    assert exc.value.status_code == 422 and not state["starts"]


@pytest.mark.parametrize(
    "extra",
    [
        {"command": "anything"},
        {"url": "https://example.com"},
        {"root": "/tmp"},
        {"profile": "unreviewed"},
        {"deadline_at": "2026-10-31T10:00:00"},
    ],
)
def test_typed_request_cannot_select_arbitrary_code_sources_or_paths(setup, extra):
    _, _, body, _ = setup
    with pytest.raises(ValidationError):
        svi_prepare.Preparation.model_validate({**body.model_dump(), **extra})


@pytest.mark.parametrize(
    "vram,ram,scope,expected",
    [
        (12288, 32768, True, True),
        (4096, 32768, True, False),
        (12288, 8192, True, False),
        (12288, 32768, False, False),
    ],
)
def test_video_recommendation_checks_ram_gpu_and_resource_support(
    tmp_path, monkeypatch, vram, ram, scope, expected
):
    settings = SimpleNamespace(
        host_data_dir=lambda: tmp_path,
        video_python="",
        comfy_dir="",
        wan_model="",
        wan_text_encoder="",
        wan_vae="",
    )
    monkeypatch.setattr(svi_prepare, "get_settings", lambda: settings)
    monkeypatch.setattr(svi_environment, "QUALIFIED", True)
    monkeypatch.setattr(svi_prepare, "available", lambda: scope)
    monkeypatch.setattr(svi_prepare, "driver_supported", lambda _: True)
    monkeypatch.setattr(svi_prepare.platform, "libc_ver", lambda: ("glibc", "2.39"))
    monkeypatch.setattr(
        svi_prepare,
        "collect",
        lambda _: {"gpus": [{"index": 7, "memory_total_mib": vram}], "memory": {"total_mib": ram}},
    )
    result = svi_prepare.catalog()
    assert result["installation_available"] is expected
    assert result["recommendation"]["fits"] is expected
    assert result["recommendation"]["cpu_offload"] is True
    assert result["svi_inference_tested_now"] is False


def test_requalification_gate_blocks_adoption_of_an_already_prepared_engine(setup, monkeypatch):
    root, manager, body, _ = setup
    svi_prepare.start(manager, body)
    complete(setup)
    monkeypatch.setattr(svi_environment, "QUALIFIED", False)
    with pytest.raises(HTTPException) as exc:
        svi_prepare.adopt(manager, body.run_id, body)
    assert exc.value.status_code == 409
    assert not (root / "runtime/svi-environments/active.json").exists()


def test_default_closed_svi_catalog_never_claims_a_working_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(svi_prepare, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: tmp_path))
    monkeypatch.setattr(svi_environment, "QUALIFIED", False)
    monkeypatch.setattr(
        svi_prepare,
        "collect",
        lambda _: {"gpus": [{"index": 3, "memory_total_mib": 12288}], "memory": {"total_mib": 32768}},
    )
    monkeypatch.setattr(svi_prepare, "available", lambda: True)
    monkeypatch.setattr(svi_prepare, "driver_supported", lambda _: True)
    monkeypatch.setattr(svi_prepare.platform, "libc_ver", lambda: ("glibc", "2.39"))
    report = svi_prepare.catalog()
    assert not report["installation_available"]
    assert not report["managed_svi"]["available"]
    assert "qualified" in report["installation_notice"]
    assert report["recommendation"]["ram_mib"] == 18432
    assert report["recommendation"]["gpu_indices"] == [3]
    assert len(report["recipe"]["inputs"]) == 107
    assert not report["svi_inference_tested_now"]
