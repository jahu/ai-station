import json
import os
from uuid import uuid4

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
