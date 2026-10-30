import io
import sys
import wave

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import audio as host_audio
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from app.runs import request_cancel
from fastapi.testclient import TestClient


def wav_bytes():
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    return result.getvalue()


@pytest.fixture
def audio_bridge(tmp_path, monkeypatch):
    script = tmp_path / "speech.py"
    script.write_text("""import os, sys, wave, time, json
from pathlib import Path
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--ref')
parser.add_argument('--text')
parser.add_argument('--out')
parser.add_argument('--cfg', type=float, default=0.4)
parser.add_argument('--exaggeration', type=float, default=0.8)
parser.add_argument('--temperature', type=float, default=0.6)
options = parser.parse_args()
with Path(__file__).with_suffix('.options').open('a') as calls:
 calls.write(json.dumps(vars(options), ensure_ascii=False) + '\\n')
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['TRANSFORMERS_OFFLINE'] == '1'
assert os.environ['CUDA_VISIBLE_DEVICES'] == '7'
text = sys.argv[sys.argv.index('--text')+1]
text = text[:220]  # Simulate an installed model's per-call generation cap.
with Path(__file__).with_suffix('.calls').open('a') as calls:
 calls.write(json.dumps(text, ensure_ascii=False) + '\\n')
Path(__file__).with_suffix('.childpid').write_text(str(os.getpid()))
if text == 'wait': time.sleep(30)
if 'WAIT_CHILD' in text: time.sleep(30)
if text == 'fail': sys.exit(3)
if 'BROKEN_PART' in text: sys.exit(3)
if 'BAD_PCM' in text:
 Path(sys.argv[sys.argv.index('--out')+1]).write_bytes(b'not PCM')
 sys.exit(0)
with wave.open(sys.argv[sys.argv.index('--out')+1], 'wb') as wav:
 wav.setnchannels(1); wav.setsampwidth(2)
 wav.setframerate(16000 if 'FORMAT_CHANGE' in text else 24000)
 wav.writeframes(b'\\0\\0' * 4800)
print('speech generated')
""")
    monkeypatch.setenv("AI_STATION_CHATTERBOX_PYTHON", sys.executable)
    monkeypatch.setenv("AI_STATION_CHATTERBOX_SCRIPT", str(script))
    monkeypatch.setenv("AI_STATION_CHATTERBOX_CACHE", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()

    def hardware(_):
        return {"gpus": [{"index": 7}]}

    monkeypatch.setattr(host_app, "collect", hardware)
    monkeypatch.setattr(host_audio, "collect", hardware)
    with TestClient(host_app.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield host
    host_app.manager().shutdown()
    host_app.reset_manager()
    clear_settings_cache()


def reference(client):
    result = client.post("/api/audio/uploads", files={"file": ("../voice.wav", wav_bytes(), "audio/wav")})
    assert result.status_code == 201, result.text
    return result.json()


def test_audio_run_artifact_lineage_and_playback(audio_bridge):
    with TestClient(app) as client:
        source = reference(client)
        response = client.post(
            "/api/audio/runs", json={"text": "Witaj", "reference_artifact_id": source["id"]}
        )
        assert response.status_code == 202, response.text
        run = response.json()
        with session_factory()() as session:
            tick(session, "audio-test")
            assert session.get(Run, run["id"]).status == "succeeded"
            assert not active_locks(session)
        artifacts = client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        assert len(artifacts) == 1
        result = artifacts[0]
        assert result["type"] == "audio" and result["mime_type"] == "audio/wav"
        assert result["parent_artifact_ids"] == [source["id"]]
        assert result["metadata"]["sample_rate"] == 24000
        assert result["metadata"]["duration_seconds"] == 0.2
        file = client.get(f"/api/artifacts/{result['id']}/file")
        assert file.status_code == 200 and file.headers["content-disposition"].startswith("inline")
        assert file.content.startswith(b"RIFF")


@pytest.mark.parametrize("data", [b"bad", wav_bytes()[:-10]])
def test_invalid_audio_upload_is_rejected(data):
    with TestClient(app) as client:
        assert (
            client.post("/api/audio/uploads", files={"file": ("test.wav", data, "audio/wav")}).status_code
            == 422
        )
        assert client.get("/api/artifacts").json() == []


@pytest.mark.parametrize("delivery", [None, {}])
def test_cancel_managed_audio_releases_resources(audio_bridge, monkeypatch, delivery):
    original = RunnerClient.request

    def request(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/runs/audio":
            with session_factory()() as session:
                request_cancel(session, session.get(Run, json["run_id"]))
                session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        source = reference(client)
        run = client.post(
            "/api/audio/runs",
            json={
                "text": "wait",
                "reference_artifact_id": source["id"],
                **({"delivery": delivery} if delivery is not None else {}),
            },
        ).json()
        with session_factory()() as session:
            tick(session, "audio-test")
            assert session.get(Run, run["id"]).status == "canceled"
            assert not active_locks(session)
        assert not host_app.manager().inspect(run["id"])["alive"]
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()


def test_audio_runner_enforces_permissions_and_paths(audio_bridge):
    from uuid import uuid4

    with TestClient(app) as client:
        source = reference(client)
        body = {
            "run_id": str(uuid4()),
            "text": "hello",
            "reference_relative": source["relative_path"],
            "gpu": 7,
            "permissions": ["filesystem_read", "workspace_write"],
        }
        assert audio_bridge.post("/v1/runs/audio", json={**body, "permissions": []}).status_code == 403
        assert (
            audio_bridge.post(
                "/v1/runs/audio", json={**body, "reference_relative": "../escape.wav"}
            ).status_code
            == 403
        )
        assert audio_bridge.post("/v1/runs/audio", json={**body, "gpu": 123}).status_code == 422
        root = get_settings().data_dir
        (root / "artifacts/redirect.wav").symlink_to(root / source["relative_path"])
        assert (
            audio_bridge.post(
                "/v1/runs/audio", json={**body, "reference_relative": "artifacts/redirect.wav"}
            ).status_code
            == 403
        )
        assert audio_bridge.post("/v1/runs/audio", json={**body, "command": "arbitrary"}).status_code == 422


def test_assistant_dispatches_speech_and_returns_audio_result(audio_bridge):
    with TestClient(app) as client:
        source = reference(client)
        conversation = client.post(
            "/api/chat/conversations", json={"model": "local-test", "execution_mode": "orchestrator"}
        ).json()
        route = f"/api/chat/conversations/{conversation['id']}"
        result = client.post(
            route + "/messages",
            json={"content": "Witaj", "action": "audio.speech", "audio_artifact_id": source["id"]},
        )
        assert result.status_code == 202, result.text
        parent = result.json()
        with session_factory()() as session:
            assert tick(session, "audio-assistant-test") == parent["id"]
            child_id = tick(session, "audio-assistant-test")
            child = session.get(Run, child_id)
            assert child.status == "succeeded"
            assert child.task_id == parent["task_id"] and child.parent_run_id == parent["id"]
        result = client.get(route).json()["messages"][-1]
        assert result["task_status"] == "succeeded"
        assert result["artifacts"][0]["type"] == "audio"
        assert result["artifacts"][0]["parent_artifact_ids"] == [source["id"]]


def test_audio_runner_never_overwrites_existing_output(audio_bridge):
    from uuid import uuid4

    with TestClient(app) as client:
        source = reference(client)
        run_id = str(uuid4())
        path = get_settings().data_dir / f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing output")
        response = audio_bridge.post(
            "/v1/runs/audio",
            json={
                "run_id": run_id,
                "text": "hello",
                "reference_relative": source["relative_path"],
                "gpu": 7,
                "permissions": ["filesystem_read", "workspace_write"],
            },
        )
        assert response.status_code == 409
        assert path.read_bytes() == b"existing output"


def test_long_speech_preserves_last_sentence_and_combines_all_parts(audio_bridge):
    import json
    import os
    from pathlib import Path

    text = ("To jest kolejna część dłuższej opowieści. " * 17) + "Ostatnie zdanie musi pozostać."
    with TestClient(app) as client:
        source = reference(client)
        run = client.post(
            "/api/audio/runs", json={"text": text, "reference_artifact_id": source["id"]}
        ).json()
        with session_factory()() as session:
            tick(session, "complete-speech")
            assert session.get(Run, run["id"]).status == "succeeded"
            assert not active_locks(session)
        calls = Path(os.environ["AI_STATION_CHATTERBOX_SCRIPT"]).with_suffix(".calls")
        actual = [json.loads(line) for line in calls.read_text().splitlines()]
        assert len(actual) > 1
        assert " ".join(actual) == text
        assert actual[-1].endswith("Ostatnie zdanie musi pozostać.")
        artifacts = client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        assert len(artifacts) == 1
        output = client.get(f"/api/artifacts/{artifacts[0]['id']}/file")
        with wave.open(io.BytesIO(output.content)) as wav:
            assert wav.getnframes() == 4800 * len(actual)
        assert artifacts[0]["parent_artifact_ids"] == [source["id"]]


@pytest.mark.parametrize("failure", ["BROKEN_PART", "BAD_PCM", "FORMAT_CHANGE"])
def test_middle_speech_part_failure_never_publishes_partial_audio(audio_bridge, failure):
    text = "Pierwsze zdanie. " * 15 + failure + ". " + "Dalsze zdanie. " * 12
    with TestClient(app) as client:
        source = reference(client)
        run = client.post(
            "/api/audio/runs", json={"text": text, "reference_artifact_id": source["id"]}
        ).json()
        with session_factory()() as session:
            tick(session, "complete-speech-failure")
            assert session.get(Run, run["id"]).status == "failed"
            assert not active_locks(session)
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        output = get_settings().data_dir / f"artifacts/{run['id'][:2]}/{run['id'][2:4]}/{run['id']}.wav"
        assert not output.exists()


@pytest.mark.parametrize("delivery", [None, {}])
def test_cancel_long_speech_signals_the_wrapper_and_child(audio_bridge, monkeypatch, delivery):
    import os
    import time
    from pathlib import Path

    original = RunnerClient.request
    child_pid = None

    def request(self, method, path, json=None):
        nonlocal child_pid
        result = original(self, method, path, json)
        if path == "/v1/runs/audio":
            child = Path(os.environ["AI_STATION_CHATTERBOX_SCRIPT"]).with_suffix(".childpid")
            deadline = time.monotonic() + 5
            while not child.exists():
                assert time.monotonic() < deadline, "Expected a running speech child"
                time.sleep(0.01)
            child_pid = int(child.read_text())
            os.kill(child_pid, 0)
            with session_factory()() as session:
                request_cancel(session, session.get(Run, json["run_id"]))
                session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        source = reference(client)
        run = client.post(
            "/api/audio/runs",
            json={
                "text": "WAIT_CHILD " + "długa wypowiedź " * 25,
                "reference_artifact_id": source["id"],
                **({"delivery": delivery} if delivery is not None else {}),
            },
        ).json()
        with session_factory()() as session:
            tick(session, "complete-speech-cancel")
            assert session.get(Run, run["id"]).status == "canceled"
            assert not active_locks(session)
        assert not host_app.manager().inspect(run["id"])["alive"]
        assert child_pid is not None
        state = Path(f"/proc/{child_pid}/stat")
        assert not state.exists() or state.read_text().rsplit(") ", 1)[1].startswith("Z ")
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()


@pytest.mark.parametrize("long", [False, True])
def test_delivery_reaches_every_cli_call_and_retains_exact_text_and_provenance(audio_bridge, long):
    import json
    import os
    from pathlib import Path

    text = "Witaj, to jest próba głosu." if not long else "Zdanie dłuższej opowieści. " * 20
    delivery = {"exaggeration": 1.1, "cfg_weight": 0.25, "temperature": 0.7}
    with TestClient(app) as client:
        capabilities = client.get("/api/audio/capabilities").json()
        assert capabilities["delivery"]["version"] == "chatterbox-controls-v1"
        assert client.get("/api/runs").json() == []
        source = reference(client)
        response = client.post(
            "/api/audio/runs",
            json={
                "text": text,
                "reference_artifact_id": source["id"],
                "delivery": delivery,
            },
        )
        assert response.status_code == 202, response.text
        run = response.json()
        with session_factory()() as session:
            tick(session, "delivery-test")
            actual = session.get(Run, run["id"])
            assert actual.status == "succeeded", actual.error_message
            assert actual.parameters["text"] == text.strip()
            assert actual.parameters["delivery"] == delivery
            assert actual.parameters["delivery_source_sha256"] == capabilities["delivery"]["source_sha256"]
            assert not active_locks(session)
        script = Path(os.environ["AI_STATION_CHATTERBOX_SCRIPT"])
        calls = [json.loads(line) for line in script.with_suffix(".options").read_text().splitlines()]
        assert (len(calls) > 1) == long
        assert " ".join(call["text"] for call in calls) == text.strip()
        assert all(
            call["exaggeration"] == 1.1 and call["cfg"] == 0.25 and call["temperature"] == 0.7
            for call in calls
        )
        artifact = client.get("/api/artifacts", params={"run_id": run["id"]}).json()[0]
        assert artifact["metadata"]["speech_delivery"] == {
            **delivery,
            "source_sha256": capabilities["delivery"]["source_sha256"],
        }


@pytest.mark.parametrize(
    "delivery",
    [
        {"exaggeration": -0.1},
        {"exaggeration": 1.6},
        {"cfg_weight": 1.1},
        {"temperature": 0},
        {"temperature": 1.3},
        {"temperature": True},
        {"cfg_weight": "0.3"},
        {"command": "shell"},
        {"style": "whisper"},
    ],
)
def test_unbounded_or_invented_delivery_is_rejected_before_enqueue(delivery):
    from uuid import uuid4

    with TestClient(app) as client:
        response = client.post(
            "/api/audio/runs",
            json={
                "text": "Witaj",
                "reference_artifact_id": str(uuid4()),
                "delivery": delivery,
            },
        )
        assert response.status_code == 422
        assert client.get("/api/runs").json() == []


def test_delivery_runtime_change_between_inspection_and_dispatch_is_rejected(audio_bridge, monkeypatch):
    import os
    from pathlib import Path

    original = RunnerClient.request

    def request(self, method, path, json=None):
        if path == "/v1/runs/audio":
            script = Path(os.environ["AI_STATION_CHATTERBOX_SCRIPT"])
            script.write_text(script.read_text() + "\n# Changed after snapshot\n")
        return original(self, method, path, json)

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        source = reference(client)
        run = client.post(
            "/api/audio/runs",
            json={
                "text": "Witaj",
                "reference_artifact_id": source["id"],
                "delivery": {},
            },
        ).json()
        with session_factory()() as session:
            tick(session, "changed-delivery")
            assert session.get(Run, run["id"]).status == "failed"
            assert not active_locks(session)
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        script = Path(os.environ["AI_STATION_CHATTERBOX_SCRIPT"])
        assert not script.with_suffix(".calls").exists()


def test_unsupported_delivery_runtime_retains_standard_speech(audio_bridge, monkeypatch):
    import os
    from pathlib import Path

    script = Path(os.environ["AI_STATION_CHATTERBOX_SCRIPT"])
    script.write_text(script.read_text().replace("'--exaggeration'", "'--legacy-expression'"))
    with TestClient(app) as client:
        assert client.get("/api/audio/capabilities").json()["delivery"] is None
        source = reference(client)
        controlled = client.post(
            "/api/audio/runs",
            json={
                "text": "Witaj",
                "reference_artifact_id": source["id"],
                "delivery": {},
            },
        ).json()
        with session_factory()() as session:
            tick(session, "unsupported-delivery")
            assert session.get(Run, controlled["id"]).status == "failed"
            assert not active_locks(session)
        standard = client.post(
            "/api/audio/runs",
            json={
                "text": "Witaj",
                "reference_artifact_id": source["id"],
            },
        ).json()
        with session_factory()() as session:
            tick(session, "standard-delivery")
            assert session.get(Run, standard["id"]).status == "succeeded"


def test_delivery_schema_is_finite_and_default_request_identity_is_unchanged():
    from uuid import uuid4

    from ai_station_runner.audio import SpeechDelivery as NativeDelivery
    from app.audio_schema import SpeechDelivery, SpeechRequest
    from pydantic import ValidationError

    source = uuid4()
    assert SpeechRequest(text="Witaj", reference_artifact_id=source).model_dump(mode="json") == {
        "text": "Witaj",
        "reference_artifact_id": str(source),
        "gpu": "auto",
    }
    assert (
        SpeechDelivery.model_json_schema()["properties"] == NativeDelivery.model_json_schema()["properties"]
    )
    for cls in (SpeechDelivery, NativeDelivery):
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValidationError):
                cls(temperature=value)
