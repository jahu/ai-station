"""Managed inference/preview keep one opaque environment through ordinary Runs."""

import json
from pathlib import Path

from ai_station_runner import (
    effects_environment,
    effects_prepare,
    effects_runtime,
    effects_selection,
    memory_scope,
)
from app.api import app
from fastapi.testclient import TestClient
from test_effects import sound_bridge as sound_bridge
from test_effects import source_video, work


def test_managed_sound_freezes_environment_and_uses_it_for_bounded_preview(sound_bridge, monkeypatch):
    settings = effects_runtime.get_settings()
    identity = "b" * 64
    chosen = {
        "managed": True,
        "mmaudio_python": Path(settings.mmaudio_python).absolute(),
        "mmaudio_dir": Path(settings.mmaudio_dir).absolute(),
        "mmaudio_models": Path(settings.mmaudio_models).absolute(),
        "environment": Path(settings.mmaudio_dir).parent / "prepared",
    }
    monkeypatch.setattr(effects_selection, "selection", lambda *args: chosen)
    monkeypatch.setattr(effects_environment, "resolve_id", lambda *args: chosen)
    monkeypatch.setattr(effects_prepare, "driver_supported", lambda *args: True)
    monkeypatch.setattr(
        effects_prepare, "compatible_devices", lambda gpus: [g for g in gpus if g["index"] == 7]
    )
    monkeypatch.setattr(memory_scope, "scope_prefix", lambda rid, ram: ["/test-scope", str(ram)])
    monkeypatch.setattr(
        effects_runtime,
        "capabilities",
        lambda: {
            "available": True,
            "readiness": "ready",
            "configuration_source": "managed",
            "profile": "mmaudio_large44_bf16_v1",
            "model": "large_44k_v2",
            "model_revision": "fixed-weights",
            "source_revision": "fixed-source",
            "ram_mib": 18432,
            "vram_mib": 8192,
            "observation": "a" * 64,
            "environment_id": identity,
            "eligible_gpu_indices": [7],
        },
    )
    with TestClient(app) as api:
        aid = source_video(api)
        assert (
            api.post(
                "/api/audio/effects/runs",
                json={"video_artifact_id": aid, "prompt": "Wind", "gpu": "11"},
            ).status_code
            == 422
        )
        response = api.post("/api/audio/effects/runs", json={"video_artifact_id": aid, "prompt": "Wind"})
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["parameters"]["environment_id"] == identity
        assert run["parameters"]["managed_effects_gpu_indices"] == [7]
        assert work() == run["id"]
        result = api.get("/api/runs/" + run["id"]).json()
        assert result["status"] == "succeeded", result
        preview = api.get("/api/runs/" + result["metadata"]["effects_preview_run_id"]).json()
        assert preview["parameters"]["effects_environment_id"] == identity
        assert preview["requested_resources"] == {"ram_mib": 4096}
        assert work() == preview["id"]
        assert api.get("/api/runs/" + preview["id"]).json()["status"] == "succeeded"
        inference, finishing = sound_bridge["launches"]
        assert inference["env"]["HOME"].endswith("effects-launch/home")
        assert "LD_LIBRARY_PATH" not in inference["env"]
        assert json.loads(Path(inference["argv"][-1]).read_text())["request"]["environment_id"] == identity
        assert finishing["argv"][:2] == ["/test-scope", "4096"]
        assert (
            json.loads(Path(finishing["argv"][-1]).read_text())["request"]["effects_environment_id"]
            == identity
        )
