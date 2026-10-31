"""Typed native lifecycle with fake processes; no SDK, model, pip or GPU."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import fish_environment, fish_prepare, runtime_install
from ai_station_runner.processes import ProcessNotOwned
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = SimpleNamespace(host_data_dir=lambda: tmp_path)
    monkeypatch.setattr(runtime_install, "get_settings", lambda: settings)
    monkeypatch.setattr(fish_prepare, "get_settings", lambda: settings)
    monkeypatch.setattr(fish_prepare, "QUALIFIED", True)
    monkeypatch.setattr(fish_environment, "remember", lambda root, observation: None)
    frozen = fish_environment.recipe()
    digest = fish_environment.fingerprint(frozen)
    monkeypatch.setattr(
        fish_prepare, "catalog", lambda: {"installation_available": True, "manifest_sha256": digest}
    )
    monkeypatch.setattr(fish_prepare, "scope_prefix", lambda identity, maximum: ["fixed-scope", str(maximum)])
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

    body = fish_prepare.Preparation(
        profile=fish_environment.PROFILE,
        run_id=uuid4(),
        manifest_sha256=digest,
        permissions=sorted(fish_prepare.PERMISSIONS),
        deadline_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    return tmp_path, Manager(), body, state


def complete(setup, **changes):
    root, _, body, state = setup
    identity = str(body.run_id)
    state["processes"][identity].update(alive=False, status="exited", exit_code=0)
    relative = f"runtime/fish-environments/{body.manifest_sha256}/{identity}"
    folder = fish_environment.directory(
        root / "runtime", f"fish-environments/{body.manifest_sha256}/{identity}"
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
        fish_prepare.start(manager, body)
    result = fish_prepare.start(manager, body)
    assert result["status"] == "running" and len(state["starts"]) == 1
    command = state["starts"][0]
    assert command["argv"][:2] == ["fixed-scope", "4096"]
    assert command["argv"][-2] == "ai_station_runner.fish_environment_job"
    assert command["executor"] == "fish_environment_setup" and command["cwd"] == root
    assert command["deadline_at"] == body.deadline_at.timestamp()
    assert not {"PIP_INDEX_URL", "HTTPS_PROXY", "LD_PRELOAD"} & command["env"].keys()


def test_pre_dispatch_stop_is_durable_and_prevents_late_start(setup):
    _, manager, body, state = setup
    result = fish_prepare.cancel(manager, body.run_id, body)
    assert result["status"] == "canceled" and not result["alive"]
    assert fish_prepare.start(manager, body)["status"] == "canceled"
    assert not state["starts"] and not state["cancels"]


def test_deadline_is_immutable_and_a_late_repeat_only_inspects(setup, monkeypatch):
    _, manager, body, state = setup
    fish_prepare.start(manager, body)
    changed = body.model_copy(update={"deadline_at": body.deadline_at + timedelta(minutes=1)})
    with pytest.raises(HTTPException) as exc:
        fish_prepare.start(manager, changed)
    assert exc.value.status_code == 409
    monkeypatch.setattr(fish_prepare, "catalog", lambda: {"installation_available": False})
    monkeypatch.setattr(__import__("time"), "time", lambda: body.deadline_at.timestamp() + 1)
    assert fish_prepare.start(manager, body)["status"] == "running"
    assert len(state["starts"]) == 1


def test_complete_preparation_is_not_active_until_explicit_adoption(setup):
    root, manager, body, _ = setup
    fish_prepare.start(manager, body)
    folder = complete(setup)
    ready = fish_prepare.inspection(manager, body.run_id)
    assert ready["status"] == "succeeded" and ready["environment_prepared"]
    assert not (root / "runtime/fish-environments/active.json").exists()
    result = fish_prepare.adopt(manager, body.run_id, body)
    selected = json.loads((root / "runtime/fish-environments/active.json").read_text())
    assert selected["operation_id"] == str(body.run_id)
    assert result["environment_prepared"] and not result["fish_inference_tested_now"]
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
    fish_prepare.start(manager, body)
    complete(setup, **change)
    assert fish_prepare.inspection(manager, body.run_id)["requires_inspection"]
    with pytest.raises(HTTPException) as exc:
        fish_prepare.adopt(manager, body.run_id, body)
    assert exc.value.status_code == 409 and not (root / "runtime/fish-environments/active.json").exists()


def test_stop_serializes_against_adoption_even_if_ready_file_exists(setup):
    root, manager, body, state = setup
    fish_prepare.start(manager, body)
    complete(setup)
    assert fish_prepare.cancel(manager, body.run_id, body)["status"] == "canceled"
    with pytest.raises(HTTPException):
        fish_prepare.adopt(manager, body.run_id, body)
    assert not (root / "runtime/fish-environments/active.json").exists()
    assert state["cancels"] == [str(body.run_id)]


def test_failed_private_identity_publication_preserves_previous_active_environment(setup, monkeypatch):
    root, manager, body, _ = setup
    fish_prepare.start(manager, body)
    complete(setup)
    folder = fish_environment.directory(root / "runtime", "fish-environments")
    previous = {
        "profile": body.profile,
        "operation_id": str(uuid4()),
        "manifest_sha256": body.manifest_sha256,
    }
    runtime_install.atomic_json(folder, "active.json", previous)

    def fail(root, observation):
        assert observation["operation_id"] == str(body.run_id)
        raise OSError("Synthetic private identity publication failure")

    monkeypatch.setattr(fish_environment, "remember", fail)
    with pytest.raises(OSError, match="identity publication"):
        fish_prepare.adopt(manager, body.run_id, body)
    assert fish_environment.read_json(folder / "active.json") == previous


@pytest.mark.parametrize("field", ["fish_speech_python", "fish_speech_dir", "fish_speech_models"])
def test_partial_explicit_configuration_never_silently_uses_managed_fallback(tmp_path, monkeypatch, field):
    from ai_station_runner import fish_selection

    settings = SimpleNamespace(
        **{key: "" for key in fish_selection.FIELDS},
        host_data_dir=lambda: tmp_path,
        fish_speech_enabled=False,
    )
    setattr(settings, field, str(tmp_path / "external"))
    monkeypatch.setattr(fish_prepare, "QUALIFIED", True)

    def forbidden(*args, **kwargs):
        pytest.fail("Explicit configuration must not resolve a managed environment")

    monkeypatch.setattr(fish_environment, "resolve", forbidden)
    monkeypatch.setattr(fish_environment, "resolve_id", forbidden)
    selected = fish_selection.selection(settings, {"environment_id": "a" * 64})
    assert selected["managed"] is False and selected[field] == tmp_path / "external"
    assert all(selected[key] is None for key in fish_selection.FIELDS if key != field)


def test_journal_without_confirmed_process_requires_inspection_not_reexecution(setup):
    _, manager, body, state = setup
    fish_prepare.start(manager, body)
    state["processes"].clear()
    result = fish_prepare.start(manager, body)
    assert result["status"] == "interrupted" and result["requires_inspection"]
    assert len(state["starts"]) == 1


def test_cancel_never_signals_another_executor(setup):
    _, manager, body, state = setup
    fish_prepare.start(manager, body)
    state["processes"][str(body.run_id)]["executor"] = "unrelated"
    with pytest.raises(HTTPException) as exc:
        fish_prepare.cancel(manager, body.run_id, body)
    assert exc.value.status_code == 409 and not state["cancels"]


@pytest.mark.parametrize("stage", ["start", "cancel", "adopt"])
def test_model_network_workspace_authority_required(setup, stage):
    _, manager, body, state = setup
    body = body.model_copy(update={"permissions": ["manage_models"]})
    with pytest.raises(HTTPException) as exc:
        if stage == "start":
            fish_prepare.start(manager, body)
        else:
            getattr(fish_prepare, stage)(manager, body.run_id, body)
    assert exc.value.status_code == 403 and not state["starts"] and not state["cancels"]


def test_unqualified_installer_stays_unavailable(setup, monkeypatch):
    _, manager, body, state = setup
    monkeypatch.setattr(
        fish_prepare,
        "catalog",
        lambda: {"installation_available": False, "installation_notice": "Not qualified"},
    )
    with pytest.raises(HTTPException):
        fish_prepare.start(manager, body)
    assert not state["starts"]


@pytest.mark.parametrize("hours", [-1, 5])
def test_invalid_deadline_cannot_start_a_process(setup, hours):
    _, manager, body, state = setup
    body = body.model_copy(update={"deadline_at": datetime.now(UTC) + timedelta(hours=hours)})
    with pytest.raises(HTTPException) as exc:
        fish_prepare.start(manager, body)
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
        fish_prepare.Preparation.model_validate({**body.model_dump(), **extra})


@pytest.mark.parametrize(
    "vram,codec,ram,scope,expected",
    [
        (12288, 6144, 32768, True, True),
        (10240, 5120, 32768, True, True),
        (12288, None, 32768, True, False),
        (8192, 5120, 32768, True, False),
        (12288, 4096, 32768, True, False),
        (4096, 8192, 32768, True, False),
        (12288, 8192, 8192, True, False),
        (12288, 8192, 32768, False, False),
    ],
)
def test_fish_recommendation_checks_ram_gpu_and_resource_support(
    tmp_path, monkeypatch, vram, codec, ram, scope, expected
):
    from ai_station_runner import fish_runtime as fish

    settings = SimpleNamespace(
        host_data_dir=lambda: tmp_path,
        fish_speech_python="",
        fish_speech_dir="",
        fish_speech_models="",
        fish_speech_enabled=False,
    )
    monkeypatch.setattr(fish_prepare, "get_settings", lambda: settings)
    monkeypatch.setattr(fish_prepare, "QUALIFIED", True)
    monkeypatch.setattr(fish_prepare, "available", lambda: scope)
    monkeypatch.setattr(fish_prepare, "driver_supported", lambda _: True)
    monkeypatch.setattr(
        fish_prepare, "compatible_devices", lambda gpus: [g for g in gpus if g["memory_total_mib"] >= 5120]
    )
    monkeypatch.setattr(fish_prepare.platform, "libc_ver", lambda: ("glibc", "2.39"))
    monkeypatch.setattr(
        fish_prepare,
        "collect",
        lambda _: {
            "gpus": [{"index": 7, "memory_total_mib": vram}]
            + ([{"index": 11, "memory_total_mib": codec}] if codec is not None else []),
            "memory": {"total_mib": ram},
        },
    )
    monkeypatch.setattr(fish, "capabilities", lambda: {"available": False})
    result = fish_prepare.catalog()
    assert result["installation_available"] is expected
    assert result["recommendation"]["fits"] is expected
    assert result["recommendation"]["cpu_offload"] is False
    assert result["fish_inference_tested_now"] is False


@pytest.mark.parametrize(
    "output,code,expected",
    [("580.126.20\n580.196.07\n", 0, True), ("580.95.05\n", 0, False), ("N/A\n", 0, False), ("", 1, False)],
)
def test_driver_admission_reports_unsupported_without_changing_the_machine(
    monkeypatch, output, code, expected
):
    calls = []

    def inspect(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=output, returncode=code)

    monkeypatch.setattr(fish_prepare.subprocess, "run", inspect)
    assert fish_prepare.driver_supported("580.126.20") is expected
    assert calls[0][0] == ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]
    assert calls[0][1]["timeout"] == 5 and "shell" not in calls[0][1]


@pytest.mark.parametrize(
    "output,expected", [("7, 8.6\n11, 7.5\n", [7]), ("malformed", []), ("7, 7.5\n11, 8.9\n", [11])]
)
def test_managed_admission_uses_actual_compute_capability_not_gpu_names(monkeypatch, output, expected):
    calls = []

    def inspect(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=output, returncode=0)

    monkeypatch.setattr(fish_prepare.subprocess, "run", inspect)
    devices = [{"index": 7, "memory_total_mib": 8192}, {"index": 11, "memory_total_mib": 12288}]
    assert [v["index"] for v in fish_prepare.compatible_devices(devices)] == expected
    assert calls == [["nvidia-smi", "--query-gpu=index,compute_cap", "--format=csv,noheader,nounits"]]
