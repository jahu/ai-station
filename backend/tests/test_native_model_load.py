"""Native model Runs reuse real queue, native file inspection and shared RAM locks."""

import hashlib
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import app as host
from ai_station_runner import native_model_verify as native
from ai_station_runner import runner_platform
from ai_station_runner.gguf_context import inspect_context
from ai_station_runner.native_llama_request import NativeModelLoad
from app.api import app
from app.config import get_settings
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.models import ModelDefinition, ModelFile, ResourceLock, Run
from app.recovery import recover_stale
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_model_setup import gguf

PROFILE = "llamacpp-native-darwin-arm64-b12032-v2"


@pytest.fixture
def native_ready(monkeypatch):
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    from ai_station_runner.config import clear_settings_cache

    clear_settings_cache()
    root = get_settings().data_dir
    content = gguf()
    sha = hashlib.sha256(content).hexdigest()
    path = root / "models/store" / sha
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    path.chmod(0o444)
    stat = path.stat()
    profile = inspect_context(path, stat.st_size, stat.st_mtime)
    ram = native.memory_budget(stat.st_size, 4096, profile)
    operation = str(uuid4())
    monkeypatch.setattr(native, "platform", SimpleNamespace(system=lambda: "Darwin", machine=lambda: "arm64"))
    monkeypatch.setattr(
        native.Environment,
        "resolve_id",
        lambda self, root, identity: (
            {"observation": {"operation_id": operation, "manifest_sha256": "a" * 64}}
            if identity == "b" * 64
            else (_ for _ in ()).throw(ValueError("PRIVATE_SDK"))
        ),
    )
    monkeypatch.setattr(runner_platform, "sys", SimpleNamespace(platform="darwin"))
    state = {
        "loads": [],
        "free": 30000,
        "status": "ready",
        "lose_ack": False,
        "bad_sdk": False,
        "operation": operation,
    }
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {"gpus": [], "memory": {"total_mib": 32768, "available_mib": state["free"]}},
    )
    with control_session_factory()() as db:
        file = ModelFile(
            host_path=None,
            relative_path="models/store/" + sha,
            sha256=sha,
            filename="native-fixture.gguf",
            format="gguf",
            category="llm",
            family="qwen3",
            quantization="Q4_K_M",
            size_bytes=stat.st_size,
            mtime=stat.st_mtime,
            availability="present",
            capabilities=["chat"],
        )
        db.add(file)
        db.flush()
        definition = ModelDefinition(
            file_id=file.id,
            name="Native CPU fixture",
            family="qwen3",
            category="llm",
            capabilities=["chat"],
            status="registered",
            metadata_json={
                "gpus": [],
                "context_size": 4096,
                "cache_type": "q8_0",
                "runtime_profile": PROFILE,
                "ram_mib": ram,
                "environment_id": "b" * 64,
            },
        )
        db.add(definition)
        db.flush()
        state.update(file_id=file.id, definition_id=definition.id, ram_mib=ram)
        db.commit()

    def observation(*args):
        return {
            "status": state["status"],
            "alive": state["status"] == "ready",
            "n_ctx": 4096,
            "compute_target": "cpu",
            "memory_enforcement": "admission_only",
            "zero_swap_guaranteed": False,
            "pid": 1234,
        }

    def load(_, body):
        NativeModelLoad.model_validate(body)
        state["loads"].append(body)
        if state["lose_ack"]:
            state["lose_ack"] = False
            raise RunnerUnavailable("Synthetic lost native acknowledgment")
        state["status"] = "ready"
        return observation()

    def stop(*args):
        state["status"] = "stopped"
        return observation()

    monkeypatch.setattr(RunnerClient, "load_llama", load)
    monkeypatch.setattr(RunnerClient, "inspect_llama", observation)
    monkeypatch.setattr(RunnerClient, "stop_llama", stop)
    with TestClient(host.app) as runner:

        def request(self, method, url, json=None):
            response = runner.request(method, url, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield state
    clear_settings_cache()


def work():
    with control_session_factory()() as db:
        return tick(db, "native-model-worker")


def queue(api, state):
    response = api.post(f"/api/models/definitions/{state['definition_id']}/load", json={})
    assert response.status_code == 202, response.text
    return response.json()


def test_native_load_stop_and_restart_preserve_opaque_sdk_and_resource_contract(native_ready):
    state = native_ready
    with TestClient(app) as api:
        queued = queue(api, state)
        work()
        run = api.get("/api/runs/" + queued["id"]).json()
        assert run["status"] == "succeeded", run
        assert run["allocated_resources"]["ram_mib"] == state["ram_mib"]
        assert run["parameters"]["environment_id"] == "b" * 64
        assert "startup_deadline_at" in state["loads"][0] and "projector" not in state["loads"][0]
        assert state["operation"] not in str(run)
        with control_session_factory()() as db:
            assert len(list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))) == 1
        stopped = api.post(f"/api/llama/{queued['parameters']['instance_id']}/stop", json={})
        assert stopped.status_code == 202
        work()
        with control_session_factory()() as db:
            assert not list(db.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))
        again = api.post(f"/api/llama/{queued['parameters']['instance_id']}/restart", json={})
        assert again.status_code == 202, again.text
        work()
        assert state["loads"][-1]["environment_id"] == "b" * 64
        assert state["loads"][-1]["instance_id"] != state["loads"][0]["instance_id"]


def test_native_load_lost_ack_recovers_the_exact_request_and_retains_RAM(native_ready):
    state = native_ready
    with TestClient(app) as api:
        queued = queue(api, state)
        state["lose_ack"] = True
        work()
        with control_session_factory()() as db:
            row = db.get(Run, queued["id"])
            row.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
            assert queued["id"] in recover_stale(db)
            db.commit()
        state["free"] = 128
        work()
        assert state["loads"][0] == state["loads"][1]
        assert api.get("/api/runs/" + queued["id"]).json()["status"] == "succeeded"


def test_native_load_waits_for_ram_and_cancel_never_dispatches(native_ready):
    state = native_ready
    with TestClient(app) as api:
        queued = queue(api, state)
        state["free"] = 128
        work()
        run = api.get("/api/runs/" + queued["id"]).json()
        assert run["status"] == "queued" and run["resource_wait"]["reason"] == "memory"
        assert not state["loads"]
        assert api.post("/api/runs/" + queued["id"] + "/cancel", json={}).status_code == 200
        assert not state["loads"]


def test_native_reverification_and_saved_preset_do_not_use_a_container_image(native_ready):
    state = native_ready
    with TestClient(app) as api:
        response = api.post(f"/api/models/definitions/{state['definition_id']}/install", json={})
        assert response.status_code == 202, response.text
        work()
        run = api.get("/api/runs/" + response.json()["id"]).json()
        assert run["status"] == "succeeded", run
        definition = api.get(f"/api/models/definitions/{state['definition_id']}").json()
        assert definition["status"] == "registered"
        assert definition["preset"]["environment_id"] == "b" * 64
        assert not state["loads"]


def test_members_chat_can_plan_an_owned_relative_model_without_leaking_private_load(
    accounts, native_ready, monkeypatch
):
    from app.local_provider import LocalChatProvider

    owner, alice, bob = accounts
    state = native_ready

    async def reply(self, **kwargs):
        yield "Synthetic native private answer"

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    created = alice.post(
        "/api/chat/conversations", json={"model": "llamacpp:" + state["file_id"], "execution_mode": "chat"}
    )
    assert created.status_code == 201, created.text
    sent = alice.post(
        f"/api/chat/conversations/{created.json()['id']}/messages",
        json={"content": "Private Alice question", "web_search": {"enabled": False}},
    )
    assert sent.status_code == 202, sent.text
    for _ in range(5):
        work()
        if alice.get("/api/runs/" + sent.json()["id"]).json()["status"] in {"succeeded", "failed"}:
            break
    result = alice.get("/api/runs/" + sent.json()["id"]).json()
    assert result["status"] == "succeeded", result
    assert len(state["loads"]) == 1 and state["loads"][0]["environment_id"] == "b" * 64
    with control_session_factory()() as db:
        load = db.scalar(select(Run).where(Run.executor_type == "llama_load"))
        assert load.owner_id == db.get(Run, sent.json()["id"]).owner_id
        private_load = load.id
    assert bob.get("/api/runs/" + private_load).status_code == 404
    shared = bob.get("/api/llama")
    assert (
        shared.status_code == 200
        and private_load not in shared.text
        and state["operation"] not in shared.text
    )
    assert "admission_only" in shared.text


@pytest.mark.parametrize(
    "field,value",
    [("model_sha256", "f" * 64), ("environment_id", "c" * 64), ("model_path", "models/store/" + "d" * 64)],
)
def test_relative_model_intent_cannot_substitute_source_or_sdk_after_planning(
    accounts, native_ready, field, value
):
    from app.data_access import DataAccessError, DataScope, ScopedSession
    from app.db import get_engine
    from app.llama import LoadModel, enqueue_load
    from app.models import User

    with control_session_factory()() as db:
        alice = db.scalar(select(User).where(User.username == "Alice")).id
    with ScopedSession(bind=get_engine(), scope=DataScope(alice)) as session:
        state = native_ready
        run = enqueue_load(
            LoadModel(
                model_file_id=state["file_id"],
                gpus=[],
                context_size=4096,
                cache_type="q8_0",
                runtime_profile=PROFILE,
                ram_mib=state["ram_mib"],
                environment_id="b" * 64,
            ),
            session,
        )
        run.parameters = {**run.parameters, field: value}
        with pytest.raises(DataAccessError):
            session.flush()
        session.rollback()
    assert not native_ready["loads"]
