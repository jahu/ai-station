import hashlib
import json
import time
import wave
from uuid import uuid4

import pytest
from ai_station_runner import effects_contract as contract
from ai_station_runner import effects_job
from pydantic import ValidationError


def request(tmp_path):
    path = tmp_path / "artifacts/source.mp4"
    path.parent.mkdir()
    path.write_bytes(b"synthetic source")
    return {
        "run_id": str(uuid4()),
        "video": {
            "relative_path": "artifacts/source.mp4",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "frames": 33,
            "fps": 24,
            "width": 1280,
            "height": 704,
        },
        "prompt": "Wind",
        "gpu": 7,
        "observation": "a" * 64,
        "deadline_at": time.time() + 60,
        "permissions": ["filesystem_read", "workspace_write"],
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"gpu": True},
        {"command": "sh"},
        {"model_path": "/outside"},
        {"deadline_at": float("nan")},
        {"steps": 501},
        {"cfg": float("inf")},
    ],
)
def test_native_sound_request_rejects_unowned_authority(tmp_path, extra):
    with pytest.raises(ValidationError):
        contract.EffectsRequest.model_validate({**request(tmp_path), **extra})


@pytest.mark.parametrize("fault", [None, "scope", "observation", "video", "samples"])
def test_effects_entry_checks_frozen_sources_before_render_and_publishes_only_complete_pcm(
    tmp_path, monkeypatch, fault
):
    body = request(tmp_path)
    rid = body["run_id"]
    launch = tmp_path / f"runs/{rid}/effects-launch"
    launch.mkdir(parents=True)
    receipt = launch / "request.json"
    receipt.write_text(
        json.dumps(
            {
                "request": body,
                "runtime": str(tmp_path / "runtime"),
                "models": str(tmp_path / "models"),
                "python": "configured",
            }
        )
    )
    calls = []

    def scope(run_id, ram):
        assert run_id == rid and ram == 18432
        if fault == "scope":
            raise ValueError("scope mismatch")

    monkeypatch.setattr(effects_job, "require_scope", scope)
    monkeypatch.setattr(
        effects_job,
        "installation_observation",
        lambda *args: "b" * 64 if fault == "observation" else "a" * 64,
    )
    if fault == "video":
        (tmp_path / "artifacts/source.mp4").write_bytes(b"changed")

    def render(request, runtime, weights, source, work):
        calls.append(request.prompt)
        samples = 60636 if fault == "samples" else 60637
        with wave.open(str(work / "complete.wav"), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(b"\x01\x00" * samples)
        return {"verified": True, "samples": samples}

    monkeypatch.setattr(effects_job, "render", render)
    output = tmp_path / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.wav"
    if fault:
        with pytest.raises(ValueError):
            effects_job.run(receipt)
        assert not output.exists()
    else:
        effects_job.run(receipt)
        assert output.is_file() and output.stat().st_nlink == 1
        with pytest.raises(ValueError):
            effects_job.run(receipt)


def test_effects_observation_checks_exact_source_weights_and_symlinks(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    models = tmp_path / "models"
    models.mkdir()
    package = runtime / "mmaudio"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"")
    name = b"mmaudio/__init__.py"
    source = hashlib.sha256(len(name).to_bytes(4, "big") + name + hashlib.sha256(b"").digest()).hexdigest()
    monkeypatch.setattr(contract, "SOURCE_SHA256", source)
    monkeypatch.setattr(
        contract, "ASSETS", {"flow.pth": {"size": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}}
    )
    weight = models / "flow.pth"
    weight.write_bytes(b"weights")
    assert len(contract.installation_observation(runtime, models)) == 64
    weight.write_bytes(b"changed")
    with pytest.raises(ValueError, match="publisher"):
        contract.installation_observation(runtime, models)
    weight.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"weights")
    weight.symlink_to(outside)
    with pytest.raises((ValueError, PermissionError)):
        contract.installation_observation(runtime, models)
