import json
import os
from uuid import uuid4

import httpx
import pytest
from ai_station_runner import llama_runtime as llama
from ai_station_runner.config import clear_settings_cache
from fastapi import HTTPException


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    # Keep socket paths short even on long pytest temporary directory names.
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="llama-test-"))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(root))
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root / "models"))
    clear_settings_cache()
    (root / "models").mkdir()
    model = root / "models/model.gguf"
    model.write_bytes(b"GGUFtest")
    body = llama.Load(
        instance_id=uuid4(),
        run_id=uuid4(),
        model_path=str(model),
        size_bytes=model.stat().st_size,
        mtime=model.stat().st_mtime,
        gpus=[2, 7],
        permissions=["manage_models", "filesystem_read"],
    )
    monkeypatch.setattr(
        llama, "collect", lambda _: {"gpus": [{"index": 2, "uuid": "GPU-2"}, {"index": 7, "uuid": "GPU-7"}]}
    )
    state = {"item": None, "calls": []}

    def docker(*args, **kwargs):
        state["calls"].append(args)
        if args[:2] == ("image", "inspect"):
            return "sha256:" + "a" * 64
        if args[0] == "inspect":
            return json.dumps([state["item"]]) if state["item"] else None
        if args[0] == "create":
            labels = {
                args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1]
                for i, x in enumerate(args)
                if x == "--label"
            }
            state["item"] = {
                "Id": "b" * 64,
                "Config": {"Labels": labels},
                "State": {"Status": "created", "Running": False},
            }
            return "b" * 64
        if args[0] == "start":
            state["item"]["State"] = {"Status": "running", "Running": True}
        if args[0] == "stop":
            state["item"]["State"] = {"Status": "exited", "Running": False}
        if args[0] == "rm":
            state["item"] = None
        return ""

    monkeypatch.setattr(llama, "docker", docker)
    yield root, body, state
    import shutil

    shutil.rmtree(root)
    clear_settings_cache()


def test_owned_container_idempotency_multi_gpu_and_stop(runtime):
    root, body, state = runtime
    assert llama.load(body)["alive"]
    assert llama.load(body)["alive"]
    creates = [args for args in state["calls"] if args[0] == "create"]
    assert len(creates) == 1
    argv = creates[0]
    assert argv[argv.index("--gpus") + 1] == '"device=GPU-2,GPU-7"'
    assert argv[argv.index("--tensor-split") + 1] == "1,1"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--reasoning") + 1] == "off"
    assert argv[argv.index("--reasoning-budget") + 1] == "0"
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert f"type=bind,src={root}/runtime/llama/{body.instance_id}/io,dst=/runtime" in argv
    assert "--privileged" not in argv and "/var/run/docker.sock" not in str(argv)
    assert llama.stop(body.instance_id, llama.Stop(permissions=["manage_models"]))["status"] == "stopped"
    with pytest.raises(HTTPException):
        llama.load(body)


def test_stop_before_late_load_tombstones_identity(runtime):
    _, body, state = runtime
    assert llama.stop(body.instance_id, llama.Stop(permissions=["manage_models"]))["status"] == "stopped"
    with pytest.raises(HTTPException, match="409"):
        llama.load(body)
    assert not state["calls"]


def test_never_stop_unrelated_container(runtime):
    _, body, state = runtime
    llama.load(body)
    state["item"]["Config"]["Labels"] = {}
    with pytest.raises(HTTPException, match="409"):
        llama.stop(body.instance_id, llama.Stop(permissions=["manage_models"]))
    assert not any(args[0] in {"stop", "rm"} for args in state["calls"])


def test_changed_model_or_unknown_gpu_rejected_before_docker(runtime):
    _, body, state = runtime
    with pytest.raises(HTTPException, match="422"):
        llama.load(body.model_copy(update={"size_bytes": 9999}))
    with pytest.raises(HTTPException, match="422"):
        llama.load(body.model_copy(update={"gpus": [99]}))
    assert not state["calls"]


def test_model_boundary_and_container_cannot_rewrite_manifest(runtime):
    root, body, state = runtime
    outside = root / "outside.gguf"
    outside.write_bytes(b"GGUFtest")
    with pytest.raises(HTTPException, match="422"):
        llama.load(body.model_copy(update={"model_path": str(outside)}))
    assert not state["calls"]
    llama.load(body)
    create = next(args for args in state["calls"] if args[0] == "create")
    assert create[create.index("--pull") + 1] == "never"
    mounts = [create[i + 1] for i, value in enumerate(create) if value == "--mount"]
    assert all("manifest" not in mount for mount in mounts)
    assert mounts[-1].endswith("/io,dst=/runtime")
    record = llama.manifest(body.instance_id)
    assert record["container_id"] == "b" * 64


def test_q8_cache_adds_flash_attention_and_disables_fit(runtime):
    _, body, state = runtime
    llama.load(body.model_copy(update={"cache_type": "q8_0", "context_size": 8192}))
    argv = next(args for args in state["calls"] if args[0] == "create")
    assert argv[argv.index("--ctx-size") + 1] == "8192"
    assert argv[argv.index("--cache-type-k") + 1] == "q8_0"
    assert argv[argv.index("--cache-type-v") + 1] == "q8_0"
    assert argv[argv.index("--flash-attn") + 1] == "on"
    assert argv[argv.index("--fit") + 1] == "off"
    assert argv[argv.index("--gpu-layers") + 1] == "all"


def test_f16_load_does_not_set_q8_flags(runtime):
    _, body, state = runtime
    llama.load(body)
    argv = next(args for args in state["calls"] if args[0] == "create")
    assert "--cache-type-k" not in argv
    assert "--cache-type-v" not in argv
    assert "--flash-attn" not in argv
    assert "--fit" not in argv


def test_legacy_manifest_without_cache_type_compares_as_f16(runtime):
    _, body, state = runtime
    llama.load(body)
    record = llama.manifest(body.instance_id)
    request = dict(record["request"])
    request.pop("cache_type", None)
    record["request"] = request
    llama.save(llama.directory(body.instance_id), record)
    assert llama.load(body)["alive"]
    assert sum(args[0] == "create" for args in state["calls"]) == 1
    with pytest.raises(HTTPException, match="409"):
        llama.load(body.model_copy(update={"cache_type": "q8_0"}))


def test_context_bounds_rejected_by_schema(runtime):
    from pydantic import ValidationError

    _, body, state = runtime
    payload = body.model_dump()
    with pytest.raises(ValidationError):
        llama.Load(**{**payload, "context_size": 1000})
    with pytest.raises(ValidationError):
        llama.Load(**{**payload, "context_size": 262400})
    with pytest.raises(ValidationError):
        llama.Load(**{**payload, "cache_type": "q4_0"})
    assert not state["calls"]


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_query_runtime_metadata_prefers_props_n_ctx_and_drops_chat_template():
    class Client:
        def get(self, url):
            if url.endswith("/v1/models"):
                return _Response(
                    200,
                    {"data": [{"meta": {"n_ctx": 4096, "n_ctx_train": 262144, "n_params": 26895998464}}]},
                )
            if url.endswith("/props"):
                return _Response(
                    200,
                    {
                        "default_generation_settings": {"n_ctx": 32768},
                        "chat_template": "{% huge template %}",
                    },
                )
            raise httpx.HTTPError("unexpected")

    observed = llama.query_runtime_metadata(Client())
    assert observed == {"n_ctx": 32768, "n_ctx_train": 262144, "n_params": 26895998464}
    assert "chat_template" not in observed


def test_query_runtime_metadata_missing_endpoints_are_omitted():
    class Client:
        def get(self, url):
            raise httpx.HTTPError("offline")

    assert llama.query_runtime_metadata(Client()) == {}


def test_snapshot_ready_without_metadata_when_health_only(runtime, monkeypatch):
    _, body, state = runtime
    llama.load(body)
    state["item"]["State"] = {"Status": "running", "Running": True, "Pid": 9, "ExitCode": 0}

    class HealthOnly:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            if url.endswith("/health"):
                return _Response(200)
            raise httpx.HTTPError("no metadata")

    monkeypatch.setattr(httpx, "Client", HealthOnly)
    info = llama.snapshot(body.instance_id)
    assert info["status"] == "ready"
    assert "n_ctx" not in info
    assert "n_ctx_train" not in info
    assert "chat_template" not in info


def test_snapshot_records_observed_context(runtime, monkeypatch):
    _, body, state = runtime
    llama.load(body)
    state["item"]["State"] = {"Status": "running", "Running": True, "Pid": 9, "ExitCode": 0}

    class Meta:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            if url.endswith("/health"):
                return _Response(200)
            if url.endswith("/v1/models"):
                return _Response(200, {"data": [{"meta": {"n_ctx_train": 262144}}]})
            if url.endswith("/props"):
                return _Response(
                    200,
                    {"default_generation_settings": {"n_ctx": 8192}, "chat_template": "do-not-store"},
                )
            raise httpx.HTTPError("unknown")

    monkeypatch.setattr(httpx, "Client", Meta)
    info = llama.snapshot(body.instance_id)
    assert info["status"] == "ready"
    assert info["n_ctx"] == 8192
    assert info["n_ctx_train"] == 262144
    assert "chat_template" not in info


def test_failed_start_is_inspectable_and_not_restarted_on_replay(runtime, monkeypatch):
    _, body, state = runtime
    original = llama.docker

    def broken(*args, **kwargs):
        if args[0] == "start":
            state["calls"].append(args)
            raise HTTPException(503, "incompatible CUDA runtime")
        return original(*args, **kwargs)

    monkeypatch.setattr(llama, "docker", broken)
    result = llama.load(body)
    assert result["status"] == "failed"
    assert "CUDA" in result["error"]
    assert llama.load(body)["status"] == "failed"
    assert sum(args[0] == "start" for args in state["calls"]) == 1
