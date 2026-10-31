"""Managed shared readiness binds the observed environment and hides private paths."""

import json
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from ai_station_runner import effects_environment as environment
from ai_station_runner import effects_prepare, effects_selection
from ai_station_runner import effects_runtime as runtime


@pytest.mark.parametrize(
    "failure", [None, OSError("Missing /private/11111111-2222-4333-8444-555555555555/models")]
)
def test_shared_ready_identity_binds_observed_view_and_hides_private_failure(tmp_path, monkeypatch, failure):
    source, models = tmp_path / "observed/source", tmp_path / "observed/models"
    private = dict(
        profile=environment.PROFILE,
        manifest_sha256="b" * 64,
        operation_id="11111111-2222-4333-8444-555555555555",
    )
    settings = SimpleNamespace(host_data_dir=lambda: tmp_path, mmaudio_enabled=False)
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    # The active pointer has advanced while an earlier observed source remains
    # valid. Readiness must bind that source's identity, never the newer pointer.
    monkeypatch.setattr(
        effects_selection,
        "selection",
        lambda *args: {"managed": True, "mmaudio_models": tmp_path / "new/models"},
    )
    monkeypatch.setattr(runtime, "installation", lambda: (tmp_path / "python", source, models))
    monkeypatch.setattr(runtime, "devices", lambda *args: {7: 12288})
    monkeypatch.setattr(runtime, "installation_signature", lambda *args: ())
    done = Future()
    if failure:
        done.set_exception(failure)
    else:
        done.set_result("a" * 64)
    monkeypatch.setattr(runtime, "_checks", {(source, models, ()): done})
    monkeypatch.setattr(environment, "read_json", lambda *args: private)
    monkeypatch.setattr(
        environment, "resolve", lambda *args: {"mmaudio_models": models, "mmaudio_dir": source}
    )
    monkeypatch.setattr(runtime, "collect", lambda *args: {"gpus": [{"index": 7}]})
    monkeypatch.setattr(effects_prepare, "compatible_devices", lambda gpus: gpus)
    monkeypatch.setattr(effects_prepare, "driver_supported", lambda *args: True)
    value = runtime.capabilities()
    assert private["operation_id"] not in json.dumps(value) and "/private/" not in json.dumps(value)
    if failure:
        assert not value["available"] and value["readiness"] == "unavailable"
    else:
        assert value["available"] and value["environment_id"] == environment.environment_id(private)
        assert value["eligible_gpu_indices"] == [7]
