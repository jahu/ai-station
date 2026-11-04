import hashlib
import json
import wave
from uuid import uuid4

import av
import pytest
from ai_station_runner.media_compose import ClipInput, ComposeRequest, verified_path
from ai_station_runner.media_compose_job import compose
from pydantic import ValidationError


def clip(root, name, frames=17, fps=24, color=30):
    path = root / "artifacts" / name
    path.parent.mkdir(exist_ok=True)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = stream.height = 128
        stream.pix_fmt = "yuv420p"
        for n in range(frames):
            frame = av.VideoFrame(128, 128, "yuv420p")
            for plane in frame.planes:
                plane.update(bytes([(color + n) % 200 + 20]) * plane.buffer_size)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    data = path.read_bytes()
    return {
        "relative_path": "artifacts/" + name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "expected_frames": frames,
        "first_frame": 0,
        "frames": frames,
    }


def test_cpu_composition_decodes_all_frames_and_muxes_entire_canonical_audio(tmp_path):
    clips = [
        clip(tmp_path, "one.mp4", frames=81, fps=25),
        clip(tmp_path, "two.mp4", frames=17, fps=25, color=100),
    ]
    clips[-1]["frames"] = 10
    audio = tmp_path / "artifacts/speech.wav"
    samples = 91 * 48000 // 25 - 100
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\x01\x00" * samples)
    wavdata = audio.read_bytes()
    sound = {
        "relative_path": "artifacts/speech.wav",
        "size_bytes": len(wavdata),
        "sha256": hashlib.sha256(wavdata).hexdigest(),
        "samples": samples,
        "sample_rate": 48000,
    }
    request = ComposeRequest(
        run_id=uuid4(),
        clips=clips,
        fps=25,
        width=128,
        height=128,
        target_frames=91,
        audio=sound,
        permissions=["filesystem_read", "workspace_write"],
    )
    output = tmp_path / "artifacts/result.mp4"
    report = compose(
        {"root": str(tmp_path), "output": str(output), "request": request.model_dump(mode="json")}
    )
    assert report["verified"] and report["frames"] == 91 and report["audio_source_samples"] == samples
    assert output.is_file() and json.loads(output.with_suffix(".json").read_text())["verified"]


def test_cpu_composition_rejects_changed_hash_and_truncated_source(tmp_path):
    one = clip(tmp_path, "one.mp4")
    one["expected_frames"] = 33
    request = ComposeRequest(
        run_id=uuid4(),
        clips=[{**one, "frames": 17}],
        fps=24,
        width=128,
        height=128,
        target_frames=17,
        permissions=["filesystem_read", "workspace_write"],
    )
    output = tmp_path / "artifacts/failed.mp4"
    with pytest.raises(ValueError, match="Truncated"):
        compose({"root": str(tmp_path), "output": str(output), "request": request.model_dump(mode="json")})
    assert not output.exists()
    item = ClipInput.model_validate({**one, "sha256": "0" * 64})
    with pytest.raises(Exception, match="Media content changed"):
        verified_path(tmp_path, item)


@pytest.mark.parametrize(
    "field,value", [("fps", 23), ("target_frames", 18), ("width", 129), ("filter", "evil")]
)
def test_typed_composition_rejects_arbitrary_or_conflicting_inputs(tmp_path, field, value):
    one = clip(tmp_path, "one.mp4")
    payload = {
        "run_id": str(uuid4()),
        "clips": [one],
        "fps": 24,
        "width": 128,
        "height": 128,
        "target_frames": 17,
        "permissions": ["filesystem_read", "workspace_write"],
        field: value,
    }
    with pytest.raises(ValidationError):
        ComposeRequest.model_validate(payload)


def test_artifact_symlink_escape_is_refused(tmp_path):
    one = clip(tmp_path, "one.mp4")
    (tmp_path / "artifacts/alias.mp4").symlink_to(tmp_path / "artifacts/one.mp4")
    item = ClipInput.model_validate({**one, "relative_path": "artifacts/alias.mp4"})
    with pytest.raises(Exception):
        verified_path(tmp_path, item)


def test_native_api_rejects_escape_and_missing_permissions_without_start(tmp_path, monkeypatch):
    from ai_station_runner import app as host
    from ai_station_runner.config import clear_settings_cache
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_VIDEO_PYTHON", __import__("sys").executable)
    clear_settings_cache()
    one = clip(tmp_path, "one.mp4")
    payload = dict(
        run_id=str(uuid4()),
        clips=[one],
        fps=24,
        width=128,
        height=128,
        target_frames=17,
        permissions=["filesystem_read", "workspace_write"],
    )
    with TestClient(host.app) as client:
        denied = client.post("/v1/runs/media-compose", json={**payload, "permissions": []})
        assert denied.status_code == 403
        escaped = client.post(
            "/v1/runs/media-compose",
            json={**payload, "clips": [{**one, "relative_path": "artifacts/../../outside.mp4"}]},
        )
        assert escaped.status_code == 403
    assert not (tmp_path / "runs" / payload["run_id"]).exists()
    clear_settings_cache()


def test_managed_composition_uses_frozen_environment_cpu_scope_and_private_home(tmp_path, monkeypatch):
    import sys
    import time
    from types import SimpleNamespace

    from ai_station_runner import media_compose, memory_scope, video_selection

    observation = {
        "profile": "wan22-5b-linux-x86-64-python312-v1",
        "manifest_sha256": "a" * 64,
        "environment_id": "b" * 64,
    }
    settings = SimpleNamespace(video_python="", mmaudio_enabled=False, host_data_dir=lambda: tmp_path)
    monkeypatch.setattr(media_compose, "get_settings", lambda: settings)

    def select(settings, observed):
        assert observed == observation
        return {"managed": True, "video_python": sys.executable}

    monkeypatch.setattr(video_selection, "selection", select)
    monkeypatch.setattr(memory_scope, "scope_prefix", lambda identity, ram: ["fixed-scope", str(ram)])
    monkeypatch.setattr(memory_scope, "scope_environment", lambda: {})
    monkeypatch.setenv("LD_LIBRARY_PATH", "/ambient/untrusted")
    item = clip(tmp_path, "input.mp4")
    request = ComposeRequest(
        run_id=uuid4(),
        deadline_at=time.time() + 60,
        clips=[item],
        fps=24,
        width=128,
        height=128,
        target_frames=17,
        permissions=["filesystem_read", "workspace_write"],
        managed_runtime=observation,
    )
    manager = SimpleNamespace(start=lambda **kwargs: kwargs)
    result = media_compose.start_composition(manager, request)
    assert result["argv"][:3] == ["fixed-scope", "4096", sys.executable]
    assert result["env"]["CUDA_VISIBLE_DEVICES"] == "" and "LD_LIBRARY_PATH" not in result["env"]
    assert result["env"]["HOME"] == str(result["cwd"] / "home")
    assert result["deadline_at"] == request.deadline_at
    saved = json.loads((result["cwd"] / "request.json").read_text())
    assert saved["request"]["managed_runtime"] == observation
    with pytest.raises(ValidationError, match="deadline"):
        ComposeRequest.model_validate({**request.model_dump(mode="json"), "deadline_at": None})
    legacy = request.model_copy(update={"managed_runtime": None})
    assert "managed_runtime" not in legacy.model_dump(mode="json")


def test_managed_composition_rejects_different_interpreter_before_decoding(tmp_path, monkeypatch):
    from ai_station_runner import video_environment

    monkeypatch.setattr(video_environment, "resolve_public", lambda *args: {"environment": tmp_path})
    with pytest.raises(ValueError, match="exact frozen"):
        compose({"request": {"managed_runtime": {"environment_id": "a" * 64}}, "root": str(tmp_path)})
