"""Native capability discovery and the typed UDS boundary without GPU execution."""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import app as host
from ai_station_runner import sonic_runtime as runtime
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.sonic_contract import MODEL_FILES, PROFILE
from fastapi.testclient import TestClient


def payload():
    return {
        "run_id": str(uuid4()),
        "recipe": {"id": PROFILE, "observation": "c" * 64},
        "portrait": {"relative_path": "artifacts/portrait.png", "sha256": "d" * 64, "size_bytes": 100},
        "audio": {"relative_path": "artifacts/speech.wav", "sha256": "e" * 64, "size_bytes": 96044},
        "observed_input": {
            "width": 512,
            "height": 768,
            "samples": 48000,
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
            "target_frames": 50,
            "base_frames": 25,
            "endpoint_frames": 1,
        },
        "seed": 43,
        "gpus": [7],
        "deadline_at": time.time() + 600,
        "permissions": ["filesystem_read", "workspace_write"],
    }


@pytest.fixture
def configured(tmp_path, monkeypatch):
    source, models = tmp_path / "runtime", tmp_path / "models"
    for root, names in (
        (
            source,
            [
                "sonic.py",
                "config/inference/sonic.yaml",
                "src/pipelines/pipeline_sonic.py",
                "src/dataset/test_preprocess.py",
            ],
        ),
        (models, MODEL_FILES),
    ):
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed tiny fixture")
    for key, value in {
        "AI_STATION_DATA_HOST_PATH": str(tmp_path / "data"),
        "AI_STATION_SONIC_PYTHON": sys.executable,
        "AI_STATION_SONIC_DIR": str(source),
        "AI_STATION_SONIC_MODELS": str(models),
        "AI_STATION_SONIC_WHOLE_ENABLED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    clear_settings_cache()
    runtime._observed.cache_clear()
    monkeypatch.setattr(runtime, "scope_available", lambda: True)
    monkeypatch.setattr(runtime, "collect", lambda root: {"gpus": [{"index": 7, "uuid": "GPU-test"}]})
    yield source, models
    runtime._observed.cache_clear()
    clear_settings_cache()


def test_disabled_native_profile_does_not_hash_models_or_inspect_the_gpu(monkeypatch):
    monkeypatch.setenv("AI_STATION_SONIC_WHOLE_ENABLED", "false")
    clear_settings_cache()
    monkeypatch.setattr(runtime, "collect", lambda *_: pytest.fail("Disabled profile must not probe GPUs"))
    monkeypatch.setattr(
        runtime, "current_recipe", lambda *_: pytest.fail("Disabled profile must not hash weights")
    )
    value = runtime.capabilities()
    assert value["available"] is False and "not enabled" in value["reason"]


def test_repeated_readiness_uses_stat_cache_but_replaced_weight_changes_observation(configured, monkeypatch):
    _, models = configured
    original, calls = runtime.installation_observation, []

    def observed(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(runtime, "installation_observation", observed)
    first = runtime.capabilities()
    assert first["available"] and first["recipe"]["id"] == PROFILE
    assert runtime.capabilities() == first and len(calls) == 1
    (models / MODEL_FILES[0]).write_text("FIXED tiny fixture")
    second = runtime.capabilities()
    assert second["recipe"] != first["recipe"] and len(calls) == 2


@pytest.mark.parametrize(
    "fault", ["missing-python", "missing-weight", "unbounded-scope", "missing-gpu", "symlink-import"]
)
def test_incomplete_or_changed_native_installations_are_not_operational(configured, monkeypatch, fault):
    source, models = configured
    if fault == "missing-python":
        monkeypatch.setenv("AI_STATION_SONIC_PYTHON", str(models / "not-installed"))
        clear_settings_cache()
    elif fault == "missing-weight":
        (models / MODEL_FILES[0]).unlink()
    elif fault == "unbounded-scope":
        monkeypatch.setattr(runtime, "scope_available", lambda: False)
    elif fault == "missing-gpu":
        monkeypatch.setattr(runtime, "collect", lambda root: {"gpus": []})
    else:
        # Also reject an added symlink directory after a successful cached poll.
        assert runtime.capabilities()["available"]
        (source / "src/imported").symlink_to(models, target_is_directory=True)
    assert runtime.capabilities()["available"] is False


def test_typed_route_is_disabled_without_an_explicit_installation_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_SONIC_WHOLE_ENABLED", "false")
    clear_settings_cache()
    monkeypatch.setattr(host, "manager", lambda: SimpleNamespace(data_dir=tmp_path))
    with TestClient(host.app) as client:
        assert client.get("/v1/avatar/whole-capabilities").json()["available"] is False
        response = client.post("/v1/runs/whole-avatar", json=payload())
        assert response.status_code == 409 and "not enabled" in response.json()["detail"]
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("command", "arbitrary"),
        ("model_dir", "/outside"),
        ("memory_limit", 999999),
        ("permissions", []),
        ("gpus", [True]),
        ("gpus", [1, 1]),
        ("seed", True),
    ],
)
def test_native_http_validation_cannot_be_used_as_a_shell_or_permission_escalation(
    tmp_path, monkeypatch, field, value
):
    monkeypatch.setattr(host, "manager", lambda: pytest.fail("Invalid body cannot reach process dispatch"))
    with TestClient(host.app) as client:
        response = client.post("/v1/runs/whole-avatar", json={**payload(), field: value})
        assert response.status_code == 422


def test_configured_route_uses_only_native_configuration_and_the_existing_owned_launcher(
    configured, monkeypatch
):
    from ai_station_runner import sonic_jobs

    source, models = configured
    manager = SimpleNamespace(data_dir=models.parent / "data")
    calls = []

    def start(owner, body, **options):
        calls.append((owner, body, options))
        return {"pid": 77, "executor": "sonic_whole"}

    monkeypatch.setattr(host, "manager", lambda: manager)
    monkeypatch.setattr(sonic_jobs, "_start_owned", start)
    with TestClient(host.app) as client:
        response = client.post("/v1/runs/whole-avatar", json=payload())
    assert response.status_code == 200 and response.json()["executor"] == "sonic_whole"
    owner, body, options = calls[0]
    assert owner is manager and body.permissions == ["filesystem_read", "workspace_write"]
    assert options["runtime"] == source and options["models"] == models
    assert options["python"] == Path(sys.executable).absolute()
