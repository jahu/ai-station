"""Temporary DB/fake transfers through the actual typed native bundle verifier."""

import hashlib
import os
import struct
from uuid import uuid4

import pytest
from app import hub_split_candidates, model_download_job, model_hub
from app.api import app
from app.config import get_settings
from app.db import control_session_factory
from app.engine import tick
from app.hub_model_parts import annotate
from app.models import ModelDefinition, ModelFile, ResourceLock, Run
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_model_setup import setup_bridge  # noqa: F401
from test_model_variant_advice import source


def part_bytes(index, count=2, *, context=131072):
    from test_model_setup import gguf

    fields = (
        {
            "general.architecture": "qwen3",
            "qwen3.block_count": 36,
            "qwen3.context_length": context,
            "qwen3.embedding_length": 2560,
            "qwen3.attention.head_count": 32,
            "qwen3.attention.head_count_kv": 8,
            "qwen3.attention.key_length": 128,
            "qwen3.attention.value_length": 128,
        }
        if index == 0
        else {}
    )
    header = bytearray(gguf(fields)) if fields else bytearray(b"GGUF" + struct.pack("<IQQ", 3, 0, 0))
    struct.pack_into("<Q", header, 8, 1)
    struct.pack_into("<Q", header, 16, len(fields) + 3)

    def string(value):
        data = value.encode()
        return struct.pack("<Q", len(data)) + data

    for key, kind, value in [
        ("split.no", 2, index),
        ("split.count", 2, count),
        ("split.tensors.count", 5, 2),
    ]:
        header += string(key) + struct.pack("<I", kind) + struct.pack("<H" if kind == 2 else "<i", value)
    header += string(f"blk.{index}.weight") + struct.pack("<IQIQ", 1, 32, 0, 0)
    return bytes(header) + bytes(-len(header) % 32) + bytes(128)


@pytest.fixture
def split_model(setup_bridge, monkeypatch):  # noqa: F811
    from ai_station_runner import runtime_setup

    report = source()
    values = [part_bytes(index) for index in range(2)]
    rows = [
        {
            "filename": f"Q4/Coder.Q4_K_M-{index + 1:05d}-of-00002.gguf",
            "format": "gguf",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "identity_available": True,
        }
        for index, data in enumerate(values)
    ]
    report["model_bundles"] = annotate(rows)
    report["files"] = rows[1:]
    state = {
        "report": report,
        "objects": {r["sha256"]: data for r, data in zip(rows, values)},
        "calls": [],
        "rows": rows,
    }

    async def inspect(*args):
        return report

    async def obtain(root, spec, *, check, progress, source_recovered=lambda url: None):
        check()
        state["calls"].append(spec.sha256)
        path = root / "models/store" / spec.sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(state["objects"][spec.sha256])
            # Keep a real sub-microsecond observation that SQLite JSON_QUOTE
            # shortens; shared runtime facts must preserve its original double.
            os.utime(path, ns=(1777777777123456700, 1777777777123456700))
            path.chmod(0o444)
        progress(spec.size_bytes, spec.size_bytes)
        return path

    monkeypatch.setattr(model_hub, "inspect_source", inspect)
    monkeypatch.setattr(model_download_job, "obtain", obtain)
    monkeypatch.setattr(hub_split_candidates, "INSTALLATION_QUALIFIED", True)
    monkeypatch.setattr(
        runtime_setup, "inspect_image", lambda _: {"image": {"present": True, "id": "sha256:" + "a" * 64}}
    )
    return state


def work():
    with control_session_factory()() as db:
        tick(db, "split-install-test")


def plan(api, state):
    inspected = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-model"},
    )
    assert inspected.status_code == 202, inspected.text
    work()
    record = api.get("/api/runs/" + inspected.json()["id"]).json()
    report = record["metadata"]["source_inspection"]
    planned = api.post(
        "/api/model-hub/plans",
        json={
            "client_request_id": str(uuid4()),
            "inspection_run_id": record["id"],
            "observation_sha256": report["observation_sha256"],
            "filename": state["rows"][1]["filename"],
        },
    )
    assert planned.status_code == 202, planned.text
    work()
    result = api.get("/api/runs/" + planned.json()["id"]).json()
    assert result["status"] == "succeeded", result
    return result


def download(api, planned):
    request = {
        "client_request_id": str(uuid4()),
        "plan_run_id": planned["id"],
        "manifest_sha256": planned["metadata"]["source_inspection"]["manifest_sha256"],
        "license_accepted": True,
    }
    accepted = api.post("/api/model-hub/downloads", json=request)
    assert accepted.status_code == 202, accepted.text
    assert api.post("/api/model-hub/downloads", json=request).json()["id"] == accepted.json()["id"]
    work()
    return api.get("/api/setup/downloads/" + accepted.json()["id"]).json()


def test_nonfirst_source_link_downloads_and_registers_the_complete_model(split_model):
    with TestClient(app) as api:
        planned = plan(api, split_model)
        assert not split_model["calls"]
        assessment = planned["metadata"]["source_inspection"]["files"][0]["assessment"]
        assert assessment["runtime_status"] == "supported_complete_bundle_plan"
        assert assessment["disk"]["file_bytes"] == split_model["rows"][1]["size_bytes"]
        assert assessment["disk"]["model_bundle_bytes"] == sum(r["size_bytes"] for r in split_model["rows"])
        saved = download(api, planned)
        assert saved["run"]["status"] == "succeeded", saved["run"].get("error_message")
        assert split_model["calls"] == [r["sha256"] for r in split_model["rows"]]
        item = api.get("/api/models").json()["items"][0]
        assert item["size_bytes"] == split_model["rows"][0]["size_bytes"]
        assert item["gguf_bundle"]["size_bytes"] == sum(r["size_bytes"] for r in split_model["rows"])
        assert [part["sha256"] for part in item["gguf_bundle"]["parts"]] == split_model["calls"]
        choice = api.get("/api/llama").json()["models"][0]
        assert choice["size_bytes"] == item["gguf_bundle"]["size_bytes"]
        assert any(
            m["model_ref"] == saved["model_key"] for m in api.get("/api/chat/model-catalog").json()["models"]
        )
        with control_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(ModelFile)) == 1
            definition = db.scalar(select(ModelDefinition))
            file = db.get(ModelFile, definition.file_id)
            assert file.size_bytes == split_model["rows"][0]["size_bytes"]
            assert file.filename == "Q4/Coder.Q4_K_M.gguf"
            assert len(definition.metadata_json["model_bundle"]["parts"]) == 2
            assert definition.metadata_json["bundle_proof"]["size_bytes"] == sum(
                r["size_bytes"] for r in split_model["rows"]
            )
            assert all(
                (get_settings().data_dir / "models/store" / row["sha256"]).is_file()
                for row in split_model["rows"]
            )


def test_native_part_count_disagreement_never_registers_a_model(split_model):
    # Publisher source identities can be exact while their actual split headers disagree.
    broken = part_bytes(1, 3)
    digest = hashlib.sha256(broken).hexdigest()
    row = split_model["rows"][1]
    split_model["objects"].pop(row["sha256"])
    row.update(sha256=digest, size_bytes=len(broken))
    split_model["objects"][digest] = broken
    split_model["report"]["model_bundles"] = annotate(split_model["rows"])
    with TestClient(app) as api:
        saved = download(api, plan(api, split_model))
        assert saved["run"]["status"] == "failed", saved
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelFile)) == 0
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 0


@pytest.mark.parametrize("native_context", [65536, 262144])
def test_native_context_can_differ_from_publisher_if_it_covers_reviewed_preset(split_model, native_context):
    data = part_bytes(0, context=native_context)
    row = split_model["rows"][0]
    split_model["objects"].pop(row["sha256"])
    row.update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
    split_model["objects"][row["sha256"]] = data
    split_model["report"]["model_bundles"] = annotate(split_model["rows"])
    with TestClient(app) as api:
        saved = download(api, plan(api, split_model))
        assert saved["run"]["status"] == "succeeded", saved["run"].get("error_message")
        definition = api.get("/api/models/definitions").json()["items"][0]
        assert definition["preset"]["context_size"] <= 32768
        assert f"{native_context:,}" in definition["context_notice"]
    with control_session_factory()() as db:
        definition = db.scalar(select(ModelDefinition))
        assert (
            definition.metadata_json["bundle_proof"]["context_profile"]["trained_context"] == native_context
        )


def test_native_limit_below_reviewed_context_cannot_register_silently_smaller_model(split_model):
    data = part_bytes(0, context=16384)
    row = split_model["rows"][0]
    split_model["objects"].pop(row["sha256"])
    row.update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
    split_model["objects"][row["sha256"]] = data
    split_model["report"]["model_bundles"] = annotate(split_model["rows"])
    with TestClient(app) as api:
        saved = download(api, plan(api, split_model))
        assert saved["run"]["status"] == "failed"
        assert "below the reviewed" in saved["run"]["error_message"]
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 0


def test_accepted_host_container_timestamp_tolerance_preserves_exact_bundle_coordinate(
    split_model, monkeypatch
):
    from app.model_sources import source_of
    from app.runner_client import RunnerClient

    original = RunnerClient.verify_model

    def verify(self, payload):
        result = original(self, payload)
        result["mtime"] += 0.0005
        return result

    monkeypatch.setattr(RunnerClient, "verify_model", verify)
    with TestClient(app) as api:
        saved = download(api, plan(api, split_model))
        assert saved["run"]["status"] == "succeeded", saved["run"].get("error_message")
    with control_session_factory()() as db:
        model = db.scalar(select(ModelFile))
        coordinate = source_of(model, db)
        assert coordinate["mtime"] == coordinate["model_bundle"]["parts"][0]["mtime"]


def test_ordinary_load_and_chat_freeze_all_parts_and_release_gpu_ram_on_stop(split_model, monkeypatch):
    from ai_station_runner.llama_runtime import Load
    from app.local_provider import LocalChatProvider
    from app.runner_client import RunnerClient

    requests = []

    def loaded(self, payload):
        Load.model_validate(payload)
        requests.append(payload)
        return {
            "status": "ready",
            "alive": True,
            "runner_id": "fake-bundle",
            "container_id": "c" * 64,
            "gpus": payload["gpus"],
            "n_ctx": payload["context_size"],
        }

    def stopped(self, identity):
        return {"status": "stopped", "alive": False, "runner_id": "fake-bundle", "container_id": "c" * 64}

    async def stream(self, **params):
        yield "Complete model response."

    monkeypatch.setattr(RunnerClient, "load_llama", loaded)
    monkeypatch.setattr(RunnerClient, "stop_llama", stopped)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        saved = download(api, plan(api, split_model))
        assert saved["run"]["status"] == "succeeded", saved["run"].get("error_message")
        with control_session_factory()() as db:
            model = db.scalar(select(ModelFile))
            model_id = model.id
        enqueued = api.post(
            "/api/llama/load",
            json={"model_file_id": model_id, "gpus": [7], "context_size": 32768, "cache_type": "q8_0"},
        )
        assert enqueued.status_code == 202, enqueued.text
        assert not requests
        work()
        loaded_run = api.get("/api/runs/" + enqueued.json()["id"]).json()
        assert loaded_run["status"] == "succeeded", loaded_run.get("error_message")
        assert len(requests) == 1
        assert len(requests[0]["model_bundle"]["parts"]) == 2
        assert requests[0]["size_bytes"] == split_model["rows"][0]["size_bytes"]
        with control_session_factory()() as db:
            active = db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))).all()
            assert {r.resource_key for r in active} == {"gpu:7", "ram:" + loaded_run["id"]}
        conversation = api.post("/api/chat/conversations", json={"model": saved["model_key"]}).json()
        reply = api.post(
            "/api/chat/conversations/" + conversation["id"] + "/messages",
            json={"content": "Hello", "web_search": {"enabled": False}},
        )
        assert reply.status_code == 202, reply.text
        work()
        assert api.get("/api/runs/" + reply.json()["id"]).json()["status"] == "succeeded"
        instance_id = loaded_run["parameters"]["instance_id"]
        stopped = api.post("/api/llama/" + instance_id + "/stop")
        assert stopped.status_code == 202, stopped.text
        work()
        assert api.get("/api/runs/" + stopped.json()["id"]).json()["status"] == "succeeded"
    with control_session_factory()() as db:
        assert not db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))).all()
        assert len(db.scalars(select(Run).where(Run.executor_type == "llama_load")).all()) == 1


def test_failed_second_part_resumes_the_same_frozen_set_without_replacing_cached_first(
    split_model, monkeypatch
):
    from app.model_download_files import SourceUnavailable

    original = model_download_job.obtain
    unavailable = True

    async def obtain(root, spec, **kwargs):
        if unavailable and spec.sha256 == split_model["rows"][1]["sha256"]:
            raise SourceUnavailable("Synthetic interruption before the second part")
        return await original(root, spec, **kwargs)

    monkeypatch.setattr(model_download_job, "obtain", obtain)
    with TestClient(app) as api:
        failed = download(api, plan(api, split_model))
        assert failed["run"]["status"] == "failed" and failed["resume_allowed"]
        first = get_settings().data_dir / "models/store" / split_model["rows"][0]["sha256"]
        observation = (first.stat().st_ino, first.stat().st_mtime_ns, first.read_bytes())
        with control_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 0
        unavailable = False
        resumed = api.post(
            "/api/setup/downloads/" + failed["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": failed["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        work()
        complete = api.get("/api/setup/downloads/" + failed["id"]).json()
        assert complete["run"]["status"] == "succeeded", complete["run"].get("error_message")
        assert complete["entry"] == failed["entry"] and complete["attempt"] == 2
        assert (first.stat().st_ino, first.stat().st_mtime_ns, first.read_bytes()) == observation
        assert complete["run"]["metadata"]["model_download"]["expected_bytes"] == sum(
            row["size_bytes"] for row in split_model["rows"]
        )


def test_stop_between_parts_preserves_cached_files_and_cannot_register_a_fragment(split_model, monkeypatch):
    from app.models import Task
    from app.task_control import cancel_task

    original = model_download_job.obtain

    async def obtain(root, spec, **kwargs):
        if spec.sha256 == split_model["rows"][1]["sha256"]:
            with control_session_factory()() as db:
                run = db.scalar(
                    select(Run).where(Run.executor_type == "model_download", Run.status == "running")
                )
                cancel_task(db, db.get(Task, run.task_id))
                db.commit()
        return await original(root, spec, **kwargs)

    monkeypatch.setattr(model_download_job, "obtain", obtain)
    with TestClient(app) as api:
        stopped = download(api, plan(api, split_model))
        assert stopped["run"]["status"] == "canceled", stopped["run"].get("error_message")
        assert len(split_model["calls"]) == 1
        root = get_settings().data_dir / "models/store"
        assert (root / split_model["rows"][0]["sha256"]).is_file()
        assert not (root / split_model["rows"][1]["sha256"]).exists()
    with control_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(ModelFile)) == 0
        assert db.scalar(select(func.count()).select_from(ModelDefinition)) == 0
