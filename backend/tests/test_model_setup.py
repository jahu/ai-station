"""Temporary database, fake weight bytes, real typed native metadata inspection."""

import hashlib
import struct
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import app as native
from ai_station_runner import llama_runtime
from ai_station_runner.config import clear_settings_cache as clear_native
from app import model_setup
from app.api import app
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import Artifact, ModelDefinition, ModelFile, Run, RuntimeInstance, Task
from app.runner_client import RunnerClient, RunnerError
from app.setup_models import CANDIDATES
from fastapi.testclient import TestClient
from sqlalchemy import select


def gguf():
    values = {
        "general.architecture": "qwen3",
        "qwen3.block_count": 36,
        "qwen3.context_length": 262144,
        "qwen3.embedding_length": 2560,
        "qwen3.attention.head_count": 32,
        "qwen3.attention.head_count_kv": 8,
        "qwen3.attention.key_length": 128,
        "qwen3.attention.value_length": 128,
    }
    result = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 0, len(values)))
    for key, value in values.items():
        encoded = key.encode()
        result += struct.pack("<Q", len(encoded)) + encoded
        if isinstance(value, str):
            encoded = value.encode()
            result += struct.pack("<IQ", 8, len(encoded)) + encoded
        else:
            result += struct.pack("<II", 4, value)
    return bytes(result)


@pytest.fixture
def setup_bridge(monkeypatch):
    from app import model_download_job
    from app.model_download_files import FileSpec

    content = gguf()
    item = CANDIDATES[0].model_copy(
        update={
            "file": FileSpec(
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                urls=("https://models.example.com/pinned.gguf",),
            )
        }
    )
    monkeypatch.setattr(model_setup, "CANDIDATES", (item,))
    monkeypatch.setattr(model_setup, "candidate", lambda value: item if value == item.id else None)
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_native()
    hardware = {
        "gpus": [{"index": 7, "name": "Synthetic GPU", "memory_total_mib": 12288, "memory_used_mib": 0}],
        "memory": {"total_mib": 32768, "available_mib": 30000},
    }
    monkeypatch.setattr(native, "collect", lambda _: hardware)
    monkeypatch.setattr(
        llama_runtime,
        "docker",
        lambda *args, **kwargs: "sha256:" + "a" * 64 if args[:2] == ("image", "inspect") else "",
    )
    calls = []

    async def obtain(root, spec, *, check, progress):
        check()
        calls.append(spec)
        path = root / "models/store" / spec.sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
            path.chmod(0o444)
        progress(len(content), len(content))
        return path

    monkeypatch.setattr(model_download_job, "obtain", obtain)
    with TestClient(native.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield {"entry": item, "calls": calls, "content": content, "hardware": hardware}
    clear_native()


def request(item):
    return {
        "client_request_id": str(uuid4()),
        "catalog_id": item.id,
        "manifest_sha256": model_setup.fingerprint(item.model_dump(mode="json")),
        "license_accepted": True,
    }


def work():
    with control_session_factory()() as db:
        return tick(db, "model-setup-test")


def test_download_is_durable_idempotent_and_registers_relative_model_without_copying_weights(setup_bridge):
    with TestClient(app) as api:
        item = setup_bridge["entry"]
        listing = api.get("/api/setup/catalog")
        assert listing.status_code == 200, listing.text
        assert listing.json()["entries"][0]["recommendation"]["gpus"] == [7]
        body = request(item)
        response = api.post("/api/setup/downloads", json=body)
        assert response.status_code == 202, response.text
        assert not setup_bridge["calls"]
        assert api.post("/api/setup/downloads", json=body).json()["id"] == response.json()["id"]
        assert work() == response.json()["run"]["id"]
        result = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert result["run"]["status"] == "succeeded", result["run"]["error_message"]
        assert result["progress"]["ready_to_try"] and result["model_key"].startswith("llamacpp:")
        assert len(setup_bridge["calls"]) == 1
        with control_session_factory()() as db:
            model = db.get(ModelFile, result["model_file_id"])
            assert model.host_path is None and model.relative_path == "models/store/" + item.file.sha256
            assert model.sha256 == item.file.sha256
            definition = db.scalar(select(ModelDefinition).where(ModelDefinition.file_id == model.id))
            assert definition.status == "registered" and definition.metadata_json["gpus"] == [7]
            outputs = list(db.scalars(select(Artifact).where(Artifact.run_id == result["run"]["id"])))
            assert len(outputs) == 1 and outputs[0].artifact_type == "json" and outputs[0].size_bytes < 10000
        assert api.get("/api/setup/downloads").json()[0]["id"] == result["id"]
        model_catalog = api.get("/api/chat/model-catalog")
        assert model_catalog.status_code == 200, model_catalog.text
        chat = api.post(
            "/api/chat/conversations", json={"execution_mode": "assistant", "model": result["model_key"]}
        )
        assert chat.status_code == 201, chat.text
        assert "AI Station" in chat.json()["model_label"]


@pytest.mark.parametrize(
    "change",
    [
        {"license_accepted": False},
        {"license_accepted": 1},
        {"manifest_sha256": "f" * 64},
        {"url": "https://arbitrary.example.com/file"},
    ],
)
def test_unreviewed_or_stale_requests_cannot_publish_download_runs(setup_bridge, change):
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json={**request(setup_bridge["entry"]), **change})
        assert response.status_code in {409, 422}, response.text
        assert api.get("/api/setup/downloads").json() == []
        assert not setup_bridge["calls"]


def test_cancel_before_claim_keeps_model_registry_unchanged(setup_bridge):
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        stopped = api.post("/api/setup/downloads/" + response.json()["id"] + "/cancel")
        assert stopped.status_code == 200, stopped.text
        work()
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile)))
        assert not setup_bridge["calls"]


def test_failed_download_resumes_frozen_recipe_in_same_task_after_catalog_changes(setup_bridge, monkeypatch):
    from app import model_download_job
    from app.model_download_files import SourceUnavailable

    original = model_download_job.obtain

    async def offline(*args, **kwargs):
        raise SourceUnavailable("Synthetic connection loss")

    monkeypatch.setattr(model_download_job, "obtain", offline)
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        failed = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert failed["run"]["status"] == "failed" and failed["resume_allowed"]
        monkeypatch.setattr(model_setup, "candidate", lambda _: None)
        monkeypatch.setattr(model_download_job, "obtain", original)
        body = {"client_request_id": str(uuid4()), "expected_run_id": failed["run"]["id"]}
        path = "/api/setup/downloads/" + failed["id"] + "/resume"
        resumed = api.post(path, json=body)
        assert resumed.status_code == 202, resumed.text
        assert api.post(path, json=body).json()["run"]["id"] == resumed.json()["run"]["id"]
        work()
        result = api.get("/api/setup/downloads/" + failed["id"]).json()
        assert result["run"]["status"] == "succeeded", result
        assert result["attempt"] == 2 and result["entry"] == failed["entry"]
        assert result["run"]["task_id"] == failed["run"]["task_id"]


def test_task_stop_during_native_inspection_cannot_register_or_publish_a_receipt(setup_bridge, monkeypatch):
    from app.task_control import cancel_task

    original = RunnerClient.verify_model

    def stop(self, payload):
        result = original(self, payload)
        with control_session_factory()() as db:
            run = db.get(Run, payload["run_id"])
            cancel_task(db, db.get(Task, run.task_id))
            db.commit()
        return result

    monkeypatch.setattr(RunnerClient, "verify_model", stop)
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        result = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert result["run"]["status"] == "canceled", result
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile)))
            assert not list(db.scalars(select(Artifact)))


@pytest.mark.parametrize("download_only", [False, True])
def test_unfitted_hardware_never_downloads_implicitly_but_explicit_files_only_is_supported(
    setup_bridge, download_only
):
    setup_bridge["hardware"]["gpus"] = []
    with TestClient(app) as api:
        response = api.post(
            "/api/setup/downloads", json={**request(setup_bridge["entry"]), "download_only": download_only}
        )
        assert response.status_code == 202, response.text
        work()
        value = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        if download_only:
            assert value["run"]["status"] == "succeeded", value
            assert value["progress"]["ready_to_try"] is False
            assert len(setup_bridge["calls"]) == 1
        else:
            assert value["run"]["status"] == "failed"
            assert "does not fit" in value["run"]["error_message"]
            assert not setup_bridge["calls"]


def test_a_second_preparation_reuses_the_immutable_file_and_shared_registry_identity(setup_bridge):
    with TestClient(app) as api:
        first = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        first = api.get("/api/setup/downloads/" + first.json()["id"]).json()
        second = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        second = api.get("/api/setup/downloads/" + second.json()["id"]).json()
        assert first["run"]["status"] == second["run"]["status"] == "succeeded", second
        assert first["model_file_id"] == second["model_file_id"]
        with control_session_factory()() as db:
            assert len(list(db.scalars(select(ModelFile)))) == 1
            assert len(list(db.scalars(select(ModelDefinition)))) == 1


def test_catalog_reports_application_storage_without_host_paths(setup_bridge, monkeypatch):
    monkeypatch.setattr(model_setup.shutil, "disk_usage", lambda _: SimpleNamespace(free=123, total=456))
    with TestClient(app) as api:
        value = api.get("/api/setup/catalog").json()
        assert value["storage"] == {"free_bytes": 123, "total_bytes": 456, "headroom_bytes": 256 * 1024**2}
        response = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        result = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert result["run"]["status"] == "failed"
        assert "Not enough free application storage" in result["run"]["error_message"]
        assert not setup_bridge["calls"]


def test_lost_worker_cannot_publish_and_explicit_resume_reuses_the_downloaded_object(
    setup_bridge, monkeypatch
):
    from app.recovery import recover_stale

    original = RunnerClient.verify_model
    interrupted = []

    def lose_lease(self, payload):
        result = original(self, payload)
        with control_session_factory()() as db:
            run = db.get(Run, payload["run_id"])
            run.lease_expires_at = utcnow() - timedelta(seconds=10)
            db.commit()
            interrupted.extend(recover_stale(db))
            db.commit()
        return result

    monkeypatch.setattr(RunnerClient, "verify_model", lose_lease)
    with TestClient(app) as api:
        response = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        value = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert value["run"]["status"] == "interrupted", value
        assert interrupted == [value["run"]["id"]]
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ModelFile)))
            assert not list(db.scalars(select(Artifact)))
        monkeypatch.setattr(RunnerClient, "verify_model", original)
        resumed = api.post(
            "/api/setup/downloads/" + value["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": value["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        work()
        result = api.get("/api/setup/downloads/" + value["id"]).json()
        assert result["attempt"] == 2 and result["run"]["status"] == "succeeded", result


def test_shared_startup_observation_retains_the_app_owned_source_identity(setup_bridge):
    from app.runtime_coordination import runtime_load_facts

    with TestClient(app) as api:
        submitted = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        value = api.get("/api/setup/downloads/" + submitted.json()["id"]).json()
        response = api.post("/api/llama/load", json={"model_file_id": value["model_file_id"], "gpus": [7]})
        assert response.status_code == 202, response.text
        with control_session_factory()() as db:
            run = db.get(Run, response.json()["id"])
            instance = db.get(RuntimeInstance, run.parameters["instance_id"])
            source = runtime_load_facts(db, instance)["source"]
            assert source["app_owned"] is True
            assert source["model_sha256"] == setup_bridge["entry"].file.sha256
            assert source["model_path"] == "models/store/" + setup_bridge["entry"].file.sha256


def test_files_prepared_before_runtime_can_be_verified_without_redownloading(setup_bridge, monkeypatch):
    from app.models import RuntimeInstance

    monkeypatch.setattr(llama_runtime, "docker", lambda *args, **kwargs: None)
    with TestClient(app) as api:
        created = api.post("/api/setup/downloads", json=request(setup_bridge["entry"]))
        work()
        value = api.get("/api/setup/downloads/" + created.json()["id"]).json()
        assert value["run"]["status"] == "succeeded" and value["progress"]["ready_to_try"] is False
        entry = api.get("/api/setup/catalog").json()["entries"][0]
        assert entry["definition_id"] and not entry["ready_to_try"]
        monkeypatch.setattr(llama_runtime, "docker", lambda *args, **kwargs: "sha256:" + "a" * 64)
        checked = api.post("/api/models/definitions/" + entry["definition_id"] + "/install", json={})
        assert checked.status_code == 202, checked.text
        work()
        assert api.get("/api/setup/catalog").json()["entries"][0]["ready_to_try"] is True
        assert len(setup_bridge["calls"]) == 1
        with control_session_factory()() as db:
            assert not list(db.scalars(select(RuntimeInstance)))


def test_larger_profiles_use_their_own_context_geometry_and_can_span_discovered_gpus():
    from app.setup_models import candidate

    entry = candidate("mlabonne-qwen3-14b-q80")
    assert entry is not None and entry.trained_context == 40960 and entry.attention_layers == 40
    one = {
        "memory": {"total_mib": 32768},
        "gpus": [{"index": 7, "memory_total_mib": 12288}],
    }
    assert model_setup.recommendation(entry, one)["fits"] is False
    two = {**one, "gpus": [*one["gpus"], {"index": 19, "memory_total_mib": 12288}]}
    preset = model_setup.recommendation(entry, two)
    assert preset["fits"] and preset["gpus"] == [7, 19]
    assert 4096 <= preset["context_size"] <= min(32768, entry.trained_context)
    assert not model_setup.recommendation(entry, {**two, "memory": {"total_mib": 8192}})["fits"]


def test_catalog_exposes_distinct_larger_quantizations_without_network_or_new_runs(monkeypatch):
    from app.setup_models import CANDIDATES, STARTER_CANDIDATE_IDS

    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"memory": {"total_mib": 32768}, "gpus": []})
    with TestClient(app) as api:
        report = api.get("/api/setup/catalog")
        assert report.status_code == 200
        entries = report.json()["entries"]
        assert len(entries) == len(CANDIDATES) == 6
        assert {row["id"] for row in entries if row["starter"]} == STARTER_CANDIDATE_IDS
        for row in entries:
            if row["starter"]:
                continue
            assert "mlabonne" in row["name"] and row["trained_context"] == 40960
            assert row["manifest_sha256"] == model_setup.fingerprint(
                next(item for item in CANDIDATES if item.id == row["id"]).model_dump(mode="json")
            )
            assert row["model_file_id"] is None and not row["ready_to_try"]
        assert api.get("/api/setup/downloads").json() == []
        with control_session_factory()() as db:
            assert list(db.scalars(select(Run))) == []
