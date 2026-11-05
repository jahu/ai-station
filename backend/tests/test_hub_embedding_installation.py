"""New encoder bundles use ordinary private plans, downloads and semantic Runs."""

import copy
import hashlib
from uuid import uuid4

import numpy as np
import pytest
from app import (
    embedding_binding,
    embedding_graph,
    embedding_recheck,
    embeddings,
    hub_embedding_install,
    model_download_job,
    model_hub,
)
from app import hub_embedding_candidates as candidates
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.models import ModelDefinition, Run
from fastapi.testclient import TestClient
from onnx import TensorProto, helper, numpy_helper
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def work():
    with control_session_factory()() as db:
        return tick(db, "encoder-test")


@pytest.fixture
def encoder(monkeypatch, tmp_path):
    graph = helper.make_graph(
        [helper.make_node("Gather", ["weights", "input_ids"], ["last_hidden_state"])],
        "synthetic",
        [
            helper.make_tensor_value_info(name, TensorProto.INT64, [1, "tokens"])
            for name in ("input_ids", "attention_mask", "token_type_ids")
        ],
        [helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, [1, "tokens", 384])],
        [numpy_helper.from_array(np.ones((10, 384), dtype=np.float32), name="weights")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    content = model.SerializeToString()
    path = tmp_path / "encoder.onnx"
    path.write_bytes(content)
    tokenizer = b'{"synthetic_tokenizer":true}'
    sha, tsha = hashlib.sha256(content).hexdigest(), hashlib.sha256(tokenizer).hexdigest()
    frozen = copy.deepcopy(embedding_graph.recipe())
    frozen.update(embedding_graph.descriptor(path))
    frozen["reference"].update(sha256=sha, size_bytes=len(content))
    frozen["tokenizer"].update(sha256=tsha, size_bytes=len(tokenizer))
    for module in (embedding_graph, embedding_binding, candidates, hub_embedding_install):
        monkeypatch.setattr(module, "recipe", lambda profile=embedding_graph.PROFILE: frozen)
    monkeypatch.setattr(candidates, "available", lambda: True)
    hardware = {"memory": {"total_mib": 32768, "available_mib": 30000}, "gpus": []}
    monkeypatch.setattr(model_hub.RunnerClient, "hardware", lambda _: hardware)
    monkeypatch.setattr(
        model_hub, "storage_info", lambda _: {"free_bytes": 50 * 1024**3, "headroom_bytes": 1024**3}
    )

    async def config(url, check):
        check()
        return frozen["configuration"]

    monkeypatch.setattr(candidates, "metadata_json", config)

    async def source(value, check):
        check()
        return {
            "repository": value.repository,
            "revision": "a" * 40,
            "source_url": f"https://huggingface.co/{value.repository}/tree/" + "a" * 40,
            "license": "mit",
            "license_url": f"https://huggingface.co/{value.repository}/blob/" + "a" * 40 + "/README.md",
            "files": [
                {
                    "filename": "encoder.onnx",
                    "format": "onnx",
                    "identity_available": True,
                    "size_bytes": len(content),
                    "sha256": sha,
                    "source_url": f"https://huggingface.co/{value.repository}/resolve/"
                    + "a" * 40
                    + "/encoder.onnx",
                }
            ],
        }

    monkeypatch.setattr(model_hub, "inspect_source", source)
    state = {
        "downloads": [],
        "opens": [],
        "hardware": hardware,
        "after_probe": None,
        "bad_graph": False,
        "reference_path": path,
        "profile": frozen,
    }

    async def obtain(root, spec, *, check, progress, source_recovered):
        check()
        state["downloads"].append(spec.sha256)
        folder = root / "models/store"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / spec.sha256
        if not path.exists():
            path.write_bytes(content if spec.sha256 == sha else tokenizer)
            path.chmod(0o400)
        progress(spec.size_bytes, spec.size_bytes)
        return path

    monkeypatch.setattr(model_download_job, "obtain", obtain)

    class Cpu:
        def __init__(self, session, run, root):
            self.run, self.root = run, root
            self.proof = None
            self.process = None

        async def open(self, *, admit=False):
            self.process = object()
            state["opens"].append((self.run.id, admit))
            _, paths = embedding_binding.objects(
                self.root, self.run.parameters["embedding_model"], rehash=True
            )
            if state["bad_graph"]:
                raise ValueError("The ONNX graph needs its own qualified encoder profile")
            self.proof = embedding_graph.inspect(paths["model"])

        async def encode(self, text, kind):
            if state["after_probe"]:
                state["after_probe"]()
            values = [0.0] * 384
            values[0 if "niebiesk" in text.lower() or "kolor" in text.lower() else 1] = 1.0
            return values

        async def close(self):
            self.process = None

    for module in (hub_embedding_install, embeddings, embedding_recheck):
        monkeypatch.setattr(module, "CpuEmbeddingProcess", Cpu)
    return state


def planned(api):
    value = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-encoder"},
    )
    assert value.status_code == 202, value.text
    work()
    run = api.get("/api/runs/" + value.json()["id"]).json()
    assert run["status"] == "succeeded", run
    report = run["metadata"]["source_inspection"]
    assert report["files"][0]["assessment"]["hardware_status"] == "estimated_fit"
    assert report["files"][0]["assessment"]["profiles"][0]["recommendation"]["gpus"] == []
    value = api.post(
        "/api/model-hub/plans",
        json={
            "client_request_id": str(uuid4()),
            "inspection_run_id": run["id"],
            "observation_sha256": report["observation_sha256"],
            "filename": "encoder.onnx",
        },
    )
    assert value.status_code == 202, value.text
    work()
    run = api.get("/api/runs/" + value.json()["id"]).json()
    assert run["status"] == "succeeded", run
    return run


def install(api):
    plan = planned(api)
    value = api.post(
        "/api/model-hub/downloads",
        json={
            "client_request_id": str(uuid4()),
            "plan_run_id": plan["id"],
            "manifest_sha256": plan["metadata"]["source_inspection"]["manifest_sha256"],
            "license_accepted": True,
        },
    )
    assert value.status_code == 202, value.text
    return value.json()


def installed(api):
    queued = install(api)
    work()
    value = api.get("/api/setup/downloads/" + queued["id"]).json()
    assert value["run"]["status"] == "succeeded", value
    assert value["definition_id"] and value["model_key"] is None
    return value


def test_bundle_installs_without_changing_encoder_then_explicit_selection_indexes_and_searches(encoder):
    with TestClient(app) as api:
        before = api.get("/api/memory/embeddings/setup").json()
        value = installed(api)
        assert len(encoder["downloads"]) == 2
        setup = api.get("/api/memory/embeddings/setup").json()
        assert setup["revision"] == before["revision"] and setup["backend"] == before["backend"]
        assert setup["registered_models"][0]["id"] == value["definition_id"]
        from app.memory import upsert_memory

        with control_session_factory()() as db:
            memory = upsert_memory(
                db,
                content="Moja pracownia jest niebieska.",
                scope="global",
                memory_type="fact",
            )
            db.commit()
            memory_id = memory.id
        response = api.post(
            "/api/memory/embeddings/models/" + value["definition_id"] + "/select",
            json={"expected_revision": setup["revision"], "confirm": True},
        )
        assert response.status_code == 202, response.text
        work()
        work()
        setup = api.get("/api/memory/embeddings/setup").json()
        assert setup["health_run"]["status"] == "succeeded", setup["health_run"]
        assert setup["index_run"]["status"] == "succeeded", setup["index_run"]
        assert (
            setup["backend"] == "registered_cpu" and setup["indexed_count"] == 1 and setup["dimension"] == 384
        )
        search = api.post("/api/memory/embeddings/search", json={"query": "Jaki kolor ma pracownia?"})
        assert search.status_code == 202, search.text
        work()
        run = api.get("/api/runs/" + search.json()["id"]).json()
        assert run["status"] == "succeeded" and run["metadata"]["results"][0]["id"] == memory_id, run
    from app.models import ResourceLock

    with control_session_factory()() as db:
        assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))


def test_invalid_graph_cannot_publish_a_shared_definition(encoder):
    encoder["bad_graph"] = True
    with TestClient(app) as api:
        queued = install(api)
        work()
        assert api.get("/api/setup/downloads/" + queued["id"]).json()["run"]["status"] == "failed"
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_changed_hardware_blocks_encoder_and_tokenizer_transfer_before_dispatch(encoder):
    with TestClient(app) as api:
        queued = install(api)
        encoder["hardware"]["memory"]["total_mib"] = 1024
        work()
        run = api.get("/api/setup/downloads/" + queued["id"]).json()["run"]
        assert run["status"] == "failed", run
    assert encoder["downloads"] == [] and encoder["opens"] == []


@pytest.mark.parametrize("probe_error", [False, True])
def test_replaced_worker_cannot_publish_a_completed_memory_health_check(encoder, probe_error):
    with TestClient(app) as api:
        value = installed(api)
        setup = api.get("/api/memory/embeddings/setup").json()
        selected = api.post(
            "/api/memory/embeddings/models/" + value["definition_id"] + "/select",
            json={"expected_revision": setup["revision"], "confirm": True},
        ).json()
        identity = selected["health_run"]["id"]

        def replace():
            with control_session_factory()() as db:
                run = db.get(Run, identity)
                run.worker_id = "replacement-worker"
                db.commit()
            if probe_error:
                raise ValueError("The old worker's probe failed after replacement")

        encoder["after_probe"] = replace
        work()
        run = api.get("/api/runs/" + identity).json()
        assert run["worker_id"] == "replacement-worker" and run["status"] == "running", run
        assert "dimension" not in run["metadata"]


def test_stop_during_probe_keeps_files_but_cannot_publish(encoder):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        queued = install(api)

        def stop():
            with control_session_factory()() as db:
                cancel_task(db, db.get(Run, queued["run"]["id"]).task)
                db.commit()

        encoder["after_probe"] = stop
        work()
        assert api.get("/api/setup/downloads/" + queued["id"]).json()["run"]["status"] == "canceled"
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_recheck_uses_existing_bundle_without_a_second_download_and_blocks_llm_presets(encoder):
    with TestClient(app) as api:
        value = installed(api)
        before = len(encoder["downloads"])
        assert (
            api.patch(
                "/api/models/definitions/" + value["definition_id"], json={"context_size": 128000}
            ).status_code
            == 422
        )
        queued = api.post("/api/models/definitions/" + value["definition_id"] + "/install", json={})
        assert queued.status_code == 202, queued.text
        work()
        run = api.get("/api/runs/" + queued.json()["id"]).json()
        assert run["status"] == "succeeded", run
        assert len(encoder["downloads"]) == before


def test_installed_choices_are_shared_but_installation_history_and_selection_authority_are_private(
    accounts, encoder
):
    owner, alice, bob = accounts
    value = installed(owner)
    assert (
        alice.get("/api/memory/embeddings/setup").json()["registered_models"][0]["id"]
        == value["definition_id"]
    )
    assert bob.get("/api/setup/downloads/" + value["id"]).status_code == 404
    response = alice.post(
        "/api/memory/embeddings/models/" + value["definition_id"] + "/select",
        json={"expected_revision": 0, "confirm": True},
    )
    assert response.status_code == 403, response.text


def test_selection_revisions_and_indexing_remain_account_private(accounts, encoder):
    owner, alice, bob = accounts
    value = installed(owner)
    for client, text in ((owner, "Moja pracownia jest niebieska"), (alice, "Tajemnica innego użytkownika")):
        response = client.post(
            "/api/memory", json={"content": text, "scope": "global", "memory_type": "fact"}
        )
        assert response.status_code == 201, response.text
    route = "/api/memory/embeddings/models/" + value["definition_id"] + "/select"
    assert owner.post(route, json={"expected_revision": 500, "confirm": True}).status_code == 409
    setup = owner.get("/api/memory/embeddings/setup").json()
    response = owner.post(route, json={"expected_revision": setup["revision"], "confirm": True})
    assert response.status_code == 202, response.text
    work()
    work()
    current = owner.get("/api/memory/embeddings/setup").json()
    assert current["memory_count"] == current["indexed_count"] == 1
    other = alice.get("/api/memory/embeddings/setup").json()
    assert other["backend"] == "registered_cpu" and other["memory_count"] == 1 and other["indexed_count"] == 0
    assert other["health_run"] is None and other["index_run"] is None


def test_selected_cpu_child_cancellation_kills_only_its_owned_process_group(encoder, monkeypatch, tmp_path):
    import asyncio
    import json
    import os
    import sys
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    from app.embedding_graph import fingerprint
    from app.embedding_process import CpuEmbeddingProcess
    from app.models import ResourceLock

    script = tmp_path / "controlled_selected_encoder.py"
    script.write_text("""import json,sys,time
from app.embedding_cpu import bind_parent
bind_parent(int(sys.argv[1]))
print(json.dumps({"ready":True,"device":"CPU","dimension":384,"model_identity":sys.argv[2]}),flush=True)
for line in sys.stdin:time.sleep(120)
""")
    original = asyncio.create_subprocess_exec
    started = []

    async def launch(*argv, **kwargs):
        assert argv[1:3] == ("-m", "app.embedding_cpu")
        config = Path(argv[-1])
        job = json.loads(config.read_text())
        assert config.parent.name == job["run_id"] and time.time() < job["deadline_at"] <= time.time() + 601
        assert "AI_STATION_LLM_API_KEY" not in kwargs["env"] and kwargs["start_new_session"]
        process = await original(
            sys.executable, str(script), str(os.getpid()), fingerprint(job["binding"]), **kwargs
        )
        started.append(process.pid)
        return process

    with TestClient(app) as api:
        value = installed(api)
        monkeypatch.setattr(embeddings, "CpuEmbeddingProcess", CpuEmbeddingProcess)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        setup = api.get("/api/memory/embeddings/setup").json()
        selected = api.post(
            "/api/memory/embeddings/models/" + value["definition_id"] + "/select",
            json={"expected_revision": setup["revision"], "confirm": True},
        ).json()
        identity = selected["health_run"]["id"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            until = time.monotonic() + 10
            while not started:
                assert time.monotonic() < until
                time.sleep(0.02)
            assert api.post("/api/runs/" + identity + "/cancel").status_code == 200
            future.result(timeout=10)
        run = api.get("/api/runs/" + identity).json()
        assert run["status"] == "canceled" and run["metadata"]["cpu_process_confirmed_gone"], run
        assert not Path(f"/proc/{started[0]}").exists()
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
