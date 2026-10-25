"""Shared image API/worker/native lifecycle with synthetic Krea inference only."""

import hashlib
import sys

import pytest
from ai_station_runner import app as native_app
from ai_station_runner import krea2_native as native
from ai_station_runner.krea2 import KreaFile
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import ModelDefinition, ModelFile, Run
from app.resources import active_locks
from fastapi.testclient import TestClient
from test_images import bridge as bridge
from test_images import upload


@pytest.fixture
def krea_bridge(bridge, tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    from ai_station_runner.config import clear_settings_cache

    clear_settings_cache()
    runtime = tmp_path / "native-runtime"
    runtime.mkdir(mode=0o700)
    python = runtime / "fake-python"
    python.write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
from PIL import Image
config=json.load(open(sys.argv[-1]))
assert os.environ['HF_HUB_OFFLINE']=='1'
assert os.environ['TRANSFORMERS_OFFLINE']=='1'
assert len(os.environ['CUDA_VISIBLE_DEVICES'].split(','))==config['gpu_count']
Image.new('RGB',(config['request']['width'],config['request']['height']),'#426c57').save(config['output'])
print('synthetic image only; no GPU inference')
"""
    )
    python.chmod(0o700)
    files = {}
    for role in ("model", "encoder", "vae", "general", "identity"):
        path = root / (role + (".gguf" if role == "model" else ".safetensors"))
        path.write_bytes(b"model")
        files[role] = KreaFile(path=str(path), size=5, sha256=hashlib.sha256(b"model").hexdigest())
    monkeypatch.setattr(
        native, "profile", lambda: (runtime, python, {k: v for k, v in files.items() if k != "model"})
    )
    hardware = {
        "gpus": [{"index": 3, "uuid": "GPU-aaaa"}, {"index": 7, "uuid": "GPU-bbbb"}],
        "memory": {"available_mib": 32768},
    }
    monkeypatch.setattr(native_app, "collect", lambda _: hardware)
    monkeypatch.setattr(native, "collect", lambda _: hardware)
    with session_factory()() as session:
        file = ModelFile(
            host_path=files["model"].path,
            filename="model.gguf",
            format="gguf",
            category="image",
            availability="present",
            size_bytes=5,
            mtime=1,
        )
        session.add(file)
        session.flush()
        model = ModelDefinition(
            name="LUSTIFY test Q4",
            category="image",
            file_id=file.id,
            status="registered",
            metadata_json={
                "image": {
                    "backend": "krea2",
                    "modes": ["t2i", "img2img", "recompose"],
                    "sha256": files["model"].sha256,
                    "profile_sha256": native.capabilities()["profile_sha256"],
                    "gpu_count": 2,
                }
            },
        )
        session.add(model)
        session.commit()
        model_id = model.id
    yield model_id


@pytest.mark.parametrize("mode,count", [("t2i", 0), ("img2img", 1), ("recompose", 1), ("recompose", 2)])
def test_krea_shared_vertical_slice(krea_bridge, mode, count):
    with TestClient(app) as client:
        parents = [upload(client) for _ in range(count)]
        response = client.post(
            "/api/images/runs",
            json={
                "mode": mode,
                "backend": "krea2",
                "model_id": krea_bridge,
                "prompt": "A red bicycle",
                "edit_prompt": "Change the wall to blue",
                "input_artifact_ids": [i["id"] for i in parents],
            },
        )
        assert response.status_code == 202, response.text
        run = response.json()
        with session_factory()() as session:
            assert tick(session, "krea-fake-worker") == run["id"]
            actual = session.get(Run, run["id"])
            assert actual.status == "succeeded", actual.error_message
            assert actual.allocated_resources["gpus"] == ["3", "7"]
            assert not active_locks(session)
        artifacts = client.get("/api/artifacts?run_id=" + run["id"]).json()
        assert len(artifacts) == 1
        assert artifacts[0]["parent_artifact_ids"] == [i["id"] for i in parents]
        assert artifacts[0]["metadata"]["image_model"]["definition_id"] == krea_bridge
        assert client.get("/api/images/runs/" + run["id"] + "/workflow").status_code == 200
        assert client.get("/api/artifacts/" + artifacts[0]["id"] + "/thumbnail").status_code == 200
