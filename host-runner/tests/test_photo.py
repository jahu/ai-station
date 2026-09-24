import argparse
import ast
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import app as module
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.photo import build_photo_argv
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "mode,backend,inputs",
    [
        ("t2i", "qwen", []),
        ("t2i", "juggernaut", []),
        ("img2img", "qwen", ["/data/in.png"]),
        ("recompose", "qwen", ["/data/a.png", "/data/b.png"]),
        ("upscale", "qwen", ["/data/in.png"]),
    ],
)
def test_argv_matches_actual_reference_parser(mode, backend, inputs):
    tree = ast.parse((Path(__file__).parents[2] / "reference/photo_pipe.py").read_text())
    parser_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_parser")
    names = {
        n.id
        for n in ast.walk(parser_node)
        if isinstance(n, ast.Name) and n.id in {"t2i", "img2img", "recompose", "upscale"}
    }
    namespace = {"argparse": argparse, **dict.fromkeys(names, lambda _: None)}
    exec(compile(ast.Module(body=[parser_node], type_ignores=[]), "<reference parser>", "exec"), namespace)
    argv = build_photo_argv(
        "/python",
        "/photo.py",
        mode=mode,
        backend=backend,
        prompt="forest",
        negative=None,
        edit_prompt="change sky",
        width=832,
        height=1216,
        steps=30,
        cfg=6,
        seed=42,
        max_side=1216,
        repeats=1,
        device="cuda:7",
        output="/data/result.png",
        inputs=inputs,
    )
    parsed = namespace["build_parser"]().parse_args(argv[2:])
    assert parsed.device == "cuda:7"
    assert parsed.out == "/data/result.png"
    if mode == "recompose":
        assert parsed.reference == [[item] for item in inputs]


def test_runner_rejects_output_redirection_and_invalid_gpu(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_PHOTO_PYTHON", "/python")
    monkeypatch.setenv("AI_STATION_PHOTO_SCRIPT", "/photo.py")
    clear_settings_cache()
    monkeypatch.setattr(module, "collect", lambda _: {"gpus": [{"index": 7}]})
    run_id = str(uuid4())
    payload = {
        "run_id": run_id,
        "mode": "t2i",
        "prompt": "forest",
        "gpu": "7",
        "output_relative": f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.png",
    }
    with TestClient(module.app) as client:
        for output in ["db/station.sqlite", "../escape.png", "artifacts/other.png"]:
            assert (
                client.post("/v1/runs/photo", json={**payload, "output_relative": output}).status_code == 422
            )
        assert client.post("/v1/runs/photo", json={**payload, "gpu": "0"}).status_code == 422
        assert client.post("/v1/runs/photo", json={**payload, "width": 50000}).status_code == 422
        (tmp_path / "db").mkdir()
        (tmp_path / "artifacts").symlink_to(tmp_path / "db", target_is_directory=True)
        assert client.post("/v1/runs/photo", json=payload).status_code == 403
    clear_settings_cache()
