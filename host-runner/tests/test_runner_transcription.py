import hashlib
import io
import json
import os
import sys
import time
import wave
from uuid import uuid4

import pytest
from ai_station_runner import transcription as tr
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.processes import ProcessManager
from ai_station_runner.transcription_protocol import audio_bytes, profile, validate_report
from fastapi.testclient import TestClient


def wav():
    data = io.BytesIO()
    with wave.open(data, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * 16000)
    return data.getvalue()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    data = tmp_path / "data"
    data.mkdir()
    model = tmp_path / "model"
    model.mkdir()
    files = {}
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        content = name.encode()
        (model / name).write_bytes(content)
        files[name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    (model / "ai-station-model.json").write_text(json.dumps({"files": files}))
    python = tmp_path / "fake-runtime"
    python.write_text(f"""#!{sys.executable}
import json,sys,pathlib,time
if "-I" in sys.argv:sys.exit(0)
rid,data,model=sys.argv[-3:]
root=pathlib.Path(data)/'runtime/transcription'/rid
b=json.loads((root/'request.json').read_text())
if (pathlib.Path(model)/'sleep').exists():time.sleep(60)
v=dict(run_id=rid,source_sha256=b['source']['sha256'],profile_sha256=b['profile_sha256'],device='cpu',language='pl',duration_seconds=1.0,text='Hello',segments=[dict(start=0,end=1,text='Hello')])
(root/'report.json').write_text(json.dumps(v))
""")
    python.chmod(0o700)
    (data / "record.wav").write_bytes(wav())
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(data))
    monkeypatch.setenv("AI_STATION_TRANSCRIPTION_PYTHON", str(python))
    monkeypatch.setenv("AI_STATION_TRANSCRIPTION_MODEL_DIR", str(model))
    clear_settings_cache()
    body = tr.TranscriptionRequest(
        run_id=uuid4(),
        permissions=sorted(tr.PERMISSIONS),
        profile_sha256=profile(model),
        source={
            "relative_path": "record.wav",
            "sha256": hashlib.sha256(wav()).hexdigest(),
            "size_bytes": len(wav()),
        },
    )
    yield data, model, body
    clear_settings_cache()


def wait(manager, rid):
    deadline = time.monotonic() + 10
    while True:
        value = manager.inspect(rid)
        if not value["alive"] and not value.get("completion_pending"):
            return value
        assert time.monotonic() < deadline
        time.sleep(0.03)


def test_owned_execution_report_replay_and_changed_request(setup):
    data, _, body = setup
    manager = ProcessManager(data)
    rid = str(body.run_id)
    first = tr.start(manager, body)
    assert tr.start(manager, body)["pid"] == first["pid"]
    assert wait(manager, rid)["exit_code"] == 0
    assert tr.report(manager, rid)["text"] == "Hello"
    assert (tr.directory(rid) / "request.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="another transcription"):
        tr.start(manager, body.model_copy(update={"language": "pl"}))


def test_permissions_typed_api_and_missing_runtime(setup, monkeypatch):
    from ai_station_runner.app import app

    body = setup[2].model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/v1/runs/transcription", json={**body, "permissions": []}).status_code == 403
        assert (
            client.post("/v1/runs/transcription", json={**body, "command": "cat /etc/passwd"}).status_code
            == 422
        )
        assert client.post("/v1/runs/transcription", json={**body, "language": "../../x"}).status_code == 422
        assert client.get("/v1/transcription/capabilities").json()["available"]
        monkeypatch.setenv("AI_STATION_TRANSCRIPTION_PYTHON", "")
        clear_settings_cache()
        assert not client.get("/v1/transcription/capabilities").json()["available"]


def test_only_owned_group_is_canceled_and_no_report_adopted(setup):
    data, model, body = setup
    (model / "sleep").touch()
    manager = ProcessManager(data, grace_seconds=0.1)
    rid = str(body.run_id)
    process = tr.start(manager, body)
    assert process["process_group_id"] != os.getpgrp()
    manager.cancel(rid)
    assert not wait(manager, rid)["alive"]
    with pytest.raises(ValueError, match="confirmed"):
        tr.report(manager, rid)


def test_model_and_audio_integrity_symlink_boundary(setup, tmp_path):
    data, model, body = setup
    (data / "record.wav").write_bytes(wav() + b"changed")
    with pytest.raises(ValueError, match="size changed"):
        tr.start(ProcessManager(data), body)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(wav())
    (data / "record.wav").unlink()
    (data / "record.wav").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        audio_bytes(data, body.source.model_dump())
    (model / "model.bin").write_bytes(b"changed!!")
    with pytest.raises(ValueError, match="manifest"):
        profile(model)


@pytest.mark.parametrize(
    "change",
    [
        {"duration_seconds": float("nan")},
        {"segments": [{"start": 0, "end": 5, "text": "Hello"}]},
        {"source_sha256": "x"},
        {"text": "invented"},
        {"device": "cuda"},
    ],
)
def test_report_rejects_untrusted_or_unbounded_output(setup, change):
    body = setup[2]
    value = dict(
        run_id=str(body.run_id),
        source_sha256=body.source.sha256,
        profile_sha256=body.profile_sha256,
        device="cpu",
        language="pl",
        duration_seconds=1,
        text="Hello",
        segments=[dict(start=0, end=1, text="Hello")],
    )
    with pytest.raises(ValueError):
        validate_report(
            {**value, **change},
            run_id=str(body.run_id),
            source_hash=body.source.sha256,
            profile_hash=body.profile_sha256,
        )


def test_native_invalid_wav_is_a_validated_rejection(setup):
    from ai_station_runner.app import app

    data, _, body = setup
    content = b"not audio"
    (data / "record.wav").write_bytes(content)
    request = body.model_dump(mode="json")
    request["source"].update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    with TestClient(app) as client:
        response = client.post("/v1/runs/transcription", json=request)
        assert response.status_code == 409, response.text


def test_optional_preprocessor_configuration_is_also_pinned(setup):
    _, model, _ = setup
    extra = model / "preprocessor_config.json"
    extra.write_bytes(b"{}")
    with pytest.raises(ValueError, match="manifest"):
        profile(model)
    manifest = model / "ai-station-model.json"
    value = json.loads(manifest.read_text())
    value["files"][extra.name] = {"size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}
    manifest.write_text(json.dumps(value))
    profile(model)
    extra.write_bytes(b"[]")
    with pytest.raises(ValueError, match="manifest"):
        profile(model)
