import hashlib
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import timeline_contract as native
from ai_station_runner import timeline_runtime as runtime
from app.timeline_schema import Manifest as PublicManifest
from pydantic import ValidationError


def test_cpu_timeline_uses_ready_managed_video_when_external_configuration_is_absent(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ai_station_runner import video_selection

    settings = SimpleNamespace(mmaudio_enabled=False, video_python="")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "available", lambda: True)
    monkeypatch.setattr(
        video_selection, "selection", lambda cfg: {"managed": True, "video_python": sys.executable}
    )
    assert runtime.installation() == __import__("pathlib").Path(sys.executable)
    monkeypatch.setattr(video_selection, "selection", lambda cfg: {"managed": False})
    with pytest.raises(ValueError, match="Configure"):
        runtime.installation()


def body(tmp_path):
    identity, run_id = str(uuid4()), str(uuid4())
    path = tmp_path / "artifacts/source.mp4"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"synthetic timeline source")
    return {
        "run_id": run_id,
        "deadline_at": time.time() + 60,
        "observation": runtime.observation(),
        "manifest": {
            "fps": 24,
            "width": 128,
            "height": 128,
            "clips": [{"artifact_id": identity, "in_frame": 0, "out_frame": 24}],
        },
        "sources": [
            {
                "artifact_id": identity,
                "kind": "video",
                "relative_path": "artifacts/source.mp4",
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "frames": 24,
                "fps": 24,
                "width": 128,
                "height": 128,
            }
        ],
        "permissions": ["filesystem_read", "workspace_write"],
    }


def test_public_and_native_manifest_contracts_cannot_drift():
    assert PublicManifest.model_json_schema() == native.Manifest.model_json_schema()


@pytest.mark.parametrize(
    "extra",
    [{"command": "sh"}, {"deadline_at": float("inf")}, {"permissions": ["full_access"]}, {"sources": []}],
)
def test_native_timeline_rejects_unbounded_authority(tmp_path, extra):
    with pytest.raises(ValidationError):
        native.TimelineRequest.model_validate({**body(tmp_path), **extra})


def test_native_timeline_journal_is_idempotent_and_retains_fixed_scope(tmp_path, monkeypatch):
    from ai_station_runner.processes import ProcessNotOwned

    monkeypatch.setattr(runtime, "installation", lambda: __import__("pathlib").Path(sys.executable))
    monkeypatch.setattr(runtime, "scope_prefix", lambda rid, ram: ["fixed-owned-scope", str(ram)])

    class Manager:
        data_dir = tmp_path
        launches = []

        def inspect(self, rid):
            if not self.launches:
                raise ProcessNotOwned("missing")
            return {"executor": "timeline_render", "pid": 123, "run_id": rid}

        def start(self, **params):
            self.launches.append(params)
            return self.inspect(params["run_id"])

    manager = Manager()
    request = native.TimelineRequest.model_validate(body(tmp_path))
    first = runtime.start(manager, request)
    assert runtime.start(manager, request) == first
    assert len(manager.launches) == 1
    sent = manager.launches[0]
    assert sent["argv"][:2] == ["fixed-owned-scope", "4096"] and sent["env"]["CUDA_VISIBLE_DEVICES"] == ""
    assert sent["deadline_at"] == request.deadline_at
    with pytest.raises(ValueError, match="identity"):
        runtime.start(manager, request.model_copy(update={"deadline_at": request.deadline_at + 1}))
