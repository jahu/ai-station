import hashlib
import json
import time
import wave
from uuid import uuid4

import pytest
from ai_station_runner import fish_contract as contract
from ai_station_runner import fish_job
from ai_station_runner.media_inputs import MediaInput
from pydantic import ValidationError


@pytest.mark.parametrize(
    "free,minimum,available",
    [(10240, 10240, True), (10239, 10240, False), (5120, 5120, True), (5000, 5120, False)],
)
def test_changed_external_gpu_usage_is_rechecked_before_weight_transfer(free, minimum, available):
    from types import SimpleNamespace

    torch = SimpleNamespace(
        cuda=SimpleNamespace(mem_get_info=lambda device: (free * 1024**2, 12288 * 1024**2))
    )
    if available:
        fish_job.require_gpu_memory(torch, 0, minimum)
    else:
        with pytest.raises(ValueError, match="other GPU workloads"):
            fish_job.require_gpu_memory(torch, 0, minimum)


def test_editable_namespace_packages_check_actual_implementation_locations(tmp_path):
    from types import SimpleNamespace

    runtime = tmp_path / "runtime"
    package = runtime / "fish_speech"
    modules = {
        "fish_speech": SimpleNamespace(__file__=None),
        "fish_speech.tokenizer": SimpleNamespace(__file__=str(package / "tokenizer.py")),
    }
    fish_job.verify_module_locations(runtime, modules)
    modules["fish_speech.tokenizer"].__file__ = str(tmp_path / "another/tokenizer.py")
    with pytest.raises(ValueError, match="another installation"):
        fish_job.verify_module_locations(runtime, modules)


def source(root):
    path = root / "artifacts/reference.wav"
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    data = path.read_bytes()
    return MediaInput(
        relative_path="artifacts/reference.wav", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"gpus": [7, 7]},
        {"gpus": [True, 9]},
        {"gpus": [-1, 9]},
        {"gpus": [7]},
        {"gpus": [7, 9, 11]},
        {"deadline_at": float("nan")},
        {"memory_max": 50000},
        {"command": "shell"},
        {"model_dir": "/private"},
        {"direction": "unsupported"},
        {"pace": "arbitrary"},
    ],
)
def test_native_request_rejects_unbounded_or_unowned_launch_settings(tmp_path, extra):
    body = {
        "run_id": uuid4(),
        "text": "Exact words",
        "reference": source(tmp_path),
        "reference_text": "Reference words",
        "observation": "a" * 64,
        "gpus": [7, 9],
        "deadline_at": time.time() + 60,
        "permissions": ["filesystem_read", "workspace_write"],
    }
    with pytest.raises(ValidationError):
        contract.FishRequest(**{**body, **extra})


def test_source_and_model_hashes_and_symlink_boundaries_are_checked(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    models = tmp_path / "models"
    models.mkdir()
    package = runtime / "fish_speech"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    name = b"fish_speech/__init__.py"
    digest = hashlib.sha256(len(name).to_bytes(4, "big") + name + hashlib.sha256(b"").digest()).hexdigest()
    monkeypatch.setattr(contract, "SOURCE_SHA256", digest)
    weight = models / "weight.bin"
    weight.write_bytes(b"weights")
    monkeypatch.setattr(
        contract, "MODEL_FILES", {"weight.bin": {"size": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}}
    )
    first = contract.installation_observation(runtime, models)
    assert len(first) == 64
    weight.write_bytes(b"changed")
    with pytest.raises(ValueError, match="model differs"):
        contract.installation_observation(runtime, models)
    weight.unlink()
    target = tmp_path / "external.bin"
    target.write_bytes(b"weights")
    weight.symlink_to(target)
    with pytest.raises((ValueError, PermissionError)):
        contract.installation_observation(runtime, models)


@pytest.mark.parametrize("fault", [None, "scope", "profile", "reference", "missing_eos"])
def test_owned_entry_validates_before_render_and_publishes_only_complete_pcm(tmp_path, monkeypatch, fault):
    reference = source(tmp_path)
    rid = str(uuid4())
    request = contract.FishRequest(
        run_id=rid,
        text="First. Last.",
        reference=reference,
        reference_text="Reference words",
        observation="a" * 64,
        gpus=[7, 9],
        deadline_at=time.time() + 60,
        permissions=["filesystem_read", "workspace_write"],
    )
    launch = tmp_path / f"runs/{rid}/fish-launch"
    launch.mkdir(parents=True)
    receipt = launch / "request.json"
    receipt.write_text(
        json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "runtime": str(tmp_path / "runtime"),
                "models": str(tmp_path / "models"),
                "python": "configured-python",
            }
        )
    )

    def scope(run_id, maximum):
        assert run_id == rid and maximum == 24576
        if fault == "scope":
            raise ValueError("scope mismatch")

    monkeypatch.setattr(fish_job, "require_scope", scope)
    monkeypatch.setattr(
        fish_job, "installation_observation", lambda *args: "b" * 64 if fault == "profile" else "a" * 64
    )
    if fault == "reference":
        (tmp_path / reference.relative_path).write_bytes(b"changed reference")
    calls = []

    def render(request, *, runtime, models, work, reference):
        calls.append(request.text)
        parts = []
        for i, text in enumerate(["First.", "Last."]):
            path = work / f"part-{i:02d}.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b"\x01\x00" * 4410)
            parts.append({"path": path.name, "text": text, "samples": 4410, "eos": fault != "missing_eos"})
        return {"sample_rate": 44100, "parts": parts}

    monkeypatch.setattr(fish_job, "render", render)
    output = tmp_path / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.wav"
    if fault:
        with pytest.raises(ValueError):
            fish_job.run(receipt)
        assert not output.exists()
        assert bool(calls) == (fault == "missing_eos")
    else:
        fish_job.run(receipt)
        with wave.open(str(output)) as wav:
            assert wav.getnframes() == 8820
        assert output.stat().st_nlink == 1
        with pytest.raises(ValueError, match="existing speech"):
            fish_job.run(receipt)
