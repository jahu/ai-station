import json
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import audio as host_audio
from ai_station_runner import fish_runtime
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import control_session_factory, session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from app.runs import request_cancel
from fastapi.testclient import TestClient
from test_audio import reference

OBSERVATION = "a" * 64


@pytest.fixture
def fish_bridge(tmp_path, monkeypatch):
    script = tmp_path / "synthetic_fish.py"
    script.write_text("""import json,os,sys,time,wave
from pathlib import Path
record=json.loads(Path(sys.argv[1]).read_text());body=record['request']
assert os.environ['HF_HUB_OFFLINE']=='1' and os.environ['TRANSFORMERS_OFFLINE']=='1'
assert set(os.environ['CUDA_VISIBLE_DEVICES'].split(','))=={'7','9'}
assert body['observation']=='a'*64
root=Path.cwd();rid=body['run_id']
(root/'native-fish-payload.json').write_text(json.dumps(body))
if body['text']=='WAIT':time.sleep(30)
if body['text']=='BROKEN_EOS':sys.exit(3)
output=root/'artifacts'/rid[:2]/rid[2:4]/(rid+'.wav');output.parent.mkdir(parents=True,exist_ok=True)
with wave.open(str(output),'wb') as wav:
 wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(44100);wav.writeframes(b'\\x01\\x00'*8820)
print('speech.chunk.completed 1/1',flush=True)
""")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("AI_STATION_FISH_SPEECH_ENABLED", "true")
    monkeypatch.setenv("AI_STATION_FISH_SPEECH_PYTHON", sys.executable)
    monkeypatch.setenv("AI_STATION_FISH_SPEECH_DIR", str(runtime))
    monkeypatch.setenv("AI_STATION_FISH_SPEECH_MODELS", str(models))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()
    fish_runtime._checks.clear()
    monkeypatch.setattr(fish_runtime, "scope_available", lambda: True)
    monkeypatch.setattr(
        fish_runtime, "scope_prefix", lambda run_id, maximum: ["/fixed-test-scope", str(maximum)]
    )
    monkeypatch.setattr(fish_runtime, "installation_signature", lambda runtime, models: ("synthetic",))
    monkeypatch.setattr(fish_runtime, "installation_observation", lambda runtime, models: OBSERVATION)
    hardware = {
        "gpus": [
            {"index": 7, "memory_total_mib": 12288, "memory_used_mib": 100},
            {"index": 9, "memory_total_mib": 8192, "memory_used_mib": 100},
        ],
        "memory": {"available_mib": 30000, "total_mib": 32768},
    }
    for module in (host_app, host_audio, fish_runtime):
        monkeypatch.setattr(module, "collect", lambda _: hardware)
    manager = host_app.manager()
    original_start = manager.start
    starts = []

    def start(**kwargs):
        assert kwargs["argv"][:2] == ["/fixed-test-scope", "24576"]
        assert kwargs["argv"][3:5] == ["-m", "ai_station_runner.fish_job"]
        assert kwargs["executor"] == "fish_speech"
        starts.append(kwargs)
        return original_start(**{**kwargs, "argv": [sys.executable, str(script), kwargs["argv"][-1]]})

    monkeypatch.setattr(manager, "start", start)
    reports = {}
    with TestClient(host_app.app) as host:

        def request(self, method, path, json=None):
            if path == "/v1/transcription/capabilities":
                return {
                    "available": True,
                    "profile_sha256": "b" * 64,
                    "formats": ["wav", "mp3"],
                    "reference_normalization": True,
                }
            if path == "/v1/runs/transcription":
                rid = json["run_id"]
                reports[rid] = {
                    "run_id": rid,
                    "source_sha256": json["source"]["sha256"],
                    "profile_sha256": json["profile_sha256"],
                    "device": "cpu",
                    "language": "pl",
                    "duration_seconds": 0.2,
                    "text": "To jest referencja głosu.",
                    "segments": [{"start": 0, "end": 0.2, "text": "To jest referencja głosu."}],
                }
                if json.get("normalize_reference") is True:
                    import numpy as np
                    from ai_station_runner.transcription_reference import save
                    from app.config import get_settings

                    root = get_settings().data_dir
                    (root / "runtime/transcription" / rid).mkdir(parents=True)
                    reports[rid]["input_format"] = "mp3"
                    reports[rid]["normalized_audio"] = save(root, rid, np.zeros(3200, dtype=np.float32))
                return {"pid": 12, "process_group_id": 12, "stdout_log": "", "stderr_log": ""}
            if (
                path.startswith("/v1/process/")
                and method == "GET"
                and path.split("?")[0].split("/")[-1] in reports
            ):
                return {
                    "alive": False,
                    "status": "exited",
                    "exit_code": 0,
                    "stdout": "",
                    "stderr": "",
                    "stdout_offset": 0,
                    "stderr_offset": 0,
                    "stdout_more": False,
                    "stderr_more": False,
                }
            if "/runs/transcription/" in path and path.endswith("/report"):
                return reports[path.split("/")[-2]]
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        deadline = time.monotonic() + 3
        while not fish_runtime.capabilities()["available"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        yield {"host": host, "starts": starts, "hardware": hardware, "reports": reports, "manager": manager}
    manager.shutdown()
    host_app.reset_manager()
    clear_settings_cache()
    fish_runtime._checks.clear()


def enqueue(client, **extra):
    source = reference(client)
    response = client.post(
        "/api/audio/runs",
        json={
            "text": "Dokładne słowa autora.",
            "reference_artifact_id": source["id"],
            "engine": "fish_s2_pro",
            "direction": "whisper",
            **extra,
        },
    )
    assert response.status_code == 202, response.text
    return response.json(), source


def work():
    with control_session_factory()() as db:
        return tick(db, "fish-test")


def test_uploaded_reference_is_transcribed_then_queued_speech_keeps_text_style_and_lineage(fish_bridge):
    with TestClient(app) as client:
        run, source = enqueue(client, pace="slow")
        assert run["executor_type"] == "fish_speech" and run["requested_resources"] == {
            "ram_mib": 24576,
            "gpu_count": 2,
        }
        asr = work()
        assert asr != run["id"] and not fish_bridge["starts"]
        prerequisite = client.get("/api/runs/" + asr).json()
        assert prerequisite["status"] == "succeeded", prerequisite["error_message"]
        assert work() == run["id"]
        actual = client.get("/api/runs/" + run["id"]).json()
        assert actual["status"] == "succeeded", actual
        assert actual["parameters"]["reference_text"] == "To jest referencja głosu."
        assert actual["parameters"]["text"] == "Dokładne słowa autora."
        assert actual["allocated_resources"]["gpus"] == ["7", "9"]
        artifacts = client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        assert len(artifacts) == 1
        assert artifacts[0]["metadata"]["speech_engine"] == "fish_s2_pro"
        assert (
            artifacts[0]["metadata"]["direction"] == "whisper" and artifacts[0]["metadata"]["pace"] == "slow"
        )
        assert artifacts[0]["parent_artifact_ids"] == [source["id"]]
        with session_factory()() as db:
            assert not active_locks(db)


def compressed_reference(client):
    response = client.post(
        "/api/audio/transcription/uploads",
        files={"file": ("phone.mp3", b"ID3" + b"\0" * 30, "audio/mpeg")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_phone_reference_normalizes_once_and_reuses_verified_wav_and_transcript(fish_bridge):
    with TestClient(app) as client:
        source = compressed_reference(client)
        body = {"text": "Dokładne słowa.", "reference_artifact_id": source["id"], "engine": "fish_s2_pro"}
        first = client.post("/api/audio/runs", json=body)
        assert first.status_code == 202, first.text
        asr = work()
        transcript = client.get("/api/runs/" + asr).json()
        assert transcript["status"] == "succeeded", transcript
        normalized = transcript["metadata"]["transcription"]["artifacts"]["reference_wav"]
        derivative = client.get("/api/artifacts/" + normalized).json()
        assert derivative["parent_artifact_ids"] == [source["id"]]
        assert derivative["mime_type"] == "audio/wav"
        assert work() == first.json()["id"]
        result = client.get("/api/runs/" + first.json()["id"]).json()
        assert result["status"] == "succeeded", result
        assert result["parameters"]["reference"]["relative_path"] == source["relative_path"]
        assert result["parameters"]["execution_reference"]["relative_path"] == derivative["relative_path"]
        assert fish_bridge["starts"][-1]["executor"] == "fish_speech"
        again = client.post("/api/audio/runs", json=body).json()
        assert again["parameters"]["reference_text_provenance"]["kind"] == "cached_asr"
        assert work() == again["id"]
        assert client.get("/api/runs/" + again["id"]).json()["status"] == "succeeded"
        assert len(fish_bridge["reports"]) == 1


def test_phone_reference_requires_capable_runner_and_keeps_chatterbox_wav_only(fish_bridge, monkeypatch):
    original = RunnerClient.request

    def older(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/transcription/capabilities":
            result.pop("reference_normalization")
        return result

    monkeypatch.setattr(RunnerClient, "request", older)
    with TestClient(app) as client:
        source = compressed_reference(client)
        body = {"text": "Hej.", "reference_artifact_id": source["id"]}
        assert client.post("/api/audio/runs", json=body).status_code == 422
        rejected = client.post("/api/audio/runs", json={**body, "engine": "fish_s2_pro"})
        assert rejected.status_code == 409, rejected.text
        assert "Update the Host Runner" in rejected.json()["detail"]
        assert not fish_bridge["reports"] and not fish_bridge["starts"]
        from app.models import Task
        from sqlalchemy import func, select

        with control_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(Run)) == 0
            assert db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.parametrize("fault", ["bytes", "trash", "missing", "long", "forged_path"])
def test_bad_canonical_reference_never_reaches_gpu(fish_bridge, fault):
    from app.config import get_settings
    from app.db import utcnow
    from app.models import Artifact

    with TestClient(app) as client:
        source = compressed_reference(client)
        submitted = client.post(
            "/api/audio/runs",
            json={"text": "Hej.", "reference_artifact_id": source["id"], "engine": "fish_s2_pro"},
        ).json()
        asr = work()
        with control_session_factory()() as db:
            transcript = db.get(Run, asr)
            report = transcript.metadata_json["transcription"]
            artifact = db.get(Artifact, report["artifacts"]["reference_wav"])
            if fault == "bytes":
                (get_settings().data_dir / artifact.relative_path).write_bytes(b"changed")
            elif fault == "trash":
                artifact.trashed_at = utcnow()
            elif fault == "missing":
                (get_settings().data_dir / artifact.relative_path).unlink()
            else:
                changed = dict(report)
                if fault == "long":
                    changed["duration_seconds"] = 61
                else:
                    changed["normalized_audio"] = {
                        **changed["normalized_audio"],
                        "relative_path": "elsewhere",
                    }
                transcript.metadata_json = {**transcript.metadata_json, "transcription": changed}
            db.commit()
        work()
        result = client.get("/api/runs/" + submitted["id"]).json()
        assert result["status"] == "failed", result
        assert not fish_bridge["starts"]


@pytest.mark.parametrize("fault", ["transcript_text", "reference_bytes"])
def test_changed_reference_or_transcript_cannot_reach_native_speech(fish_bridge, fault):
    from app.config import get_settings

    with TestClient(app) as client:
        run, source = enqueue(client)
        asr = work()
        if fault == "reference_bytes":
            path = get_settings().data_dir / source["relative_path"]
            path.write_bytes(b"changed reference")
        else:
            with control_session_factory()() as db:
                transcript = db.get(Run, asr)
                aid = transcript.metadata_json["transcription"]["artifacts"]["txt"]
                from app.models import Artifact

                artifact = db.get(Artifact, aid)
                path = get_settings().data_dir / artifact.relative_path
                path.write_text("Different words")
        work()
        actual = client.get("/api/runs/" + run["id"]).json()
        assert actual["status"] == "failed" and not fish_bridge["starts"]
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()


def test_low_vram_or_ram_waits_without_starting_a_process(fish_bridge):
    with TestClient(app) as client:
        run, _ = enqueue(client)
        work()
        fish_bridge["hardware"]["gpus"][0]["memory_used_mib"] = 7000
        work()
        assert client.get("/api/runs/" + run["id"]).json()["status"] == "queued"
        assert not fish_bridge["starts"]
        fish_bridge["hardware"]["gpus"][0]["memory_used_mib"] = 100
        fish_bridge["hardware"]["memory"]["available_mib"] = 16000
        work()
        assert client.get("/api/runs/" + run["id"]).json()["status"] == "queued"
        assert not fish_bridge["starts"]
        fish_bridge["hardware"]["memory"]["available_mib"] = 30000
        work()
        assert client.get("/api/runs/" + run["id"]).json()["status"] == "succeeded"


def test_cancellation_signals_only_the_owned_process_and_never_publishes_partial_audio(
    fish_bridge, monkeypatch
):
    original = RunnerClient.request

    def request(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/runs/fish-speech":
            with control_session_factory()() as db:
                request_cancel(db, db.get(Run, json["run_id"]))
                db.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        run, _ = enqueue(client, text="WAIT")
        work()
        work()
        assert client.get("/api/runs/" + run["id"]).json()["status"] == "canceled"
        assert not fish_bridge["manager"].inspect(run["id"])["alive"]
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        with session_factory()() as db:
            assert not active_locks(db)


def test_native_receipt_is_idempotent_and_does_not_extend_deadline(fish_bridge):
    with TestClient(app) as client:
        run, _ = enqueue(client)
        work()
        work()
        from app.config import get_settings

        body = json.loads((get_settings().data_dir / "native-fish-payload.json").read_text())
        first = fish_bridge["manager"].inspect(run["id"])
        repeat = fish_bridge["host"].post("/v1/runs/fish-speech", json=body)
        assert repeat.status_code == 200 and repeat.json()["pid"] == first["pid"]
        assert len(fish_bridge["starts"]) == 1
        changed = fish_bridge["host"].post(
            "/v1/runs/fish-speech", json={**body, "deadline_at": body["deadline_at"] + 60}
        )
        assert changed.status_code == 409 and len(fish_bridge["starts"]) == 1


def test_lost_dispatch_reply_keeps_both_gpu_leases_and_recovers_by_inspection(fish_bridge, monkeypatch):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale

    original = RunnerClient.request

    def request(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/runs/fish-speech":
            raise RunnerError(503, "Synthetic lost acknowledgement")
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        run, _ = enqueue(client, text="WAIT")
        work()
        work()
        with control_session_factory()() as db:
            actual = db.get(Run, run["id"])
            assert actual.status == "preparing"
            actual.lease_expires_at = utcnow() - timedelta(seconds=60)
            db.commit()
            recover_stale(db)
            db.commit()
            db.refresh(actual)
            assert actual.status == "preparing" and len(active_locks(db)) == 2
            assert len(fish_bridge["starts"]) == 1
            request_cancel(db, actual)
            actual.lease_expires_at = utcnow() - timedelta(seconds=60)
            db.commit()
        fish_bridge["manager"].cancel(run["id"])
        with control_session_factory()() as db:
            recover_stale(db)
            db.commit()
            assert db.get(Run, run["id"]).status == "canceled" and not active_locks(db)
        assert len(fish_bridge["starts"]) == 1


def test_native_permission_deadline_and_device_checks_do_not_start_processes(fish_bridge):
    with TestClient(app) as client:
        run, _ = enqueue(client)
        work()
        work()
        from app.config import get_settings

        body = json.loads((get_settings().data_dir / "native-fish-payload.json").read_text())
        for change, status in [
            ({"permissions": []}, 403),
            ({"deadline_at": time.time() - 1}, 409),
            ({"gpus": [7, 7]}, 422),
            ({"gpus": [7, 12]}, 409),
            ({"model_dir": "/outside"}, 422),
        ]:
            response = fish_bridge["host"].post(
                "/v1/runs/fish-speech", json={**body, "run_id": str(uuid4()), **change}
            )
            assert response.status_code == status, response.text
        assert len(fish_bridge["starts"]) == 1


def test_explicit_gpu_without_enough_total_vram_fails_instead_of_waiting_forever(fish_bridge):
    with TestClient(app) as client:
        run, _ = enqueue(client, gpu="9")
        work()
        work()
        actual = client.get("/api/runs/" + run["id"]).json()
        assert actual["status"] == "failed" and "cannot fit" in actual["error_message"]
        assert not fish_bridge["starts"]


@pytest.mark.parametrize(
    "extra", [{"direction": "invented"}, {"pace": "arbitrary"}, {"delivery": {}}, {"command": "shell"}]
)
def test_unsupported_controls_are_rejected_before_queuing(extra):
    with TestClient(app) as client:
        response = client.post(
            "/api/audio/runs",
            json={"text": "Witaj", "reference_artifact_id": str(uuid4()), "engine": "fish_s2_pro", **extra},
        )
        assert response.status_code == 422
        assert client.get("/api/runs").json() == []


def test_reviewed_speech_agent_waits_for_fish_artifact_and_reports_its_actual_result(fish_bridge):
    from app.models import Notice
    from sqlalchemy import select
    from test_agent_media import create, drain, start

    with TestClient(app) as client:
        source = reference(client)
        agent = create(
            client,
            media={
                "kind": "speech",
                "description_source": "fixed",
                "request": {
                    "text": "Dokładne słowa.",
                    "reference_artifact_id": source["id"],
                    "engine": "fish_s2_pro",
                    "direction": "whisper",
                    "pace": "slow",
                },
            },
            notification_policy={"on_success": True, "on_failure": True},
        )
        root = start(client, agent)
        with control_session_factory()() as db:
            drain(db)
            runs = list(db.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(r.status == "succeeded" for r in runs), [
                (r.executor_type, r.status, r.error_message) for r in runs
            ]
            output = next(r for r in runs if r.executor_type == "fish_speech")
            notices = list(db.scalars(select(Notice)))
            assert len(notices) == 1 and notices[0].run_id == output.id
            assert notices[0].title == "Agent media ready"
        assert client.get("/api/agents/" + agent["id"]).json()["last_status"] == "succeeded"
        assert len(client.get("/api/artifacts", params={"run_id": output.id}).json()) == 1
