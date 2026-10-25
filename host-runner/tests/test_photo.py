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


@pytest.mark.parametrize(
    "style,expected", [("prompt", ["", ""]), ("pipeline", ["portrait detail", "illustration"])]
)
def test_prompt_profile_preserves_source_cli_and_only_changes_owned_import(tmp_path, style, expected):
    import json
    import subprocess
    import sys

    script = tmp_path / "photo.py"
    source = """import json,sys
PHOTO_SUFFIX = 'portrait detail'
T2I_NEGATIVE = 'illustration'
def main():
    print(json.dumps({'style': [PHOTO_SUFFIX, T2I_NEGATIVE], 'args': sys.argv[1:]}))
if __name__ == '__main__': main()
"""
    script.write_text(source)
    argv = build_photo_argv(
        sys.executable,
        str(script),
        mode="t2i",
        backend="qwen",
        prompt="A landscape",
        negative=None,
        edit_prompt="",
        width=1280,
        height=704,
        steps=35,
        cfg=5,
        seed=None,
        max_side=None,
        repeats=None,
        device="cuda:7",
        output=str(tmp_path / "result.png"),
        inputs=[],
        prompt_style=style,
    )
    result = subprocess.run(argv, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["style"] == expected
    assert payload["args"][0] == "t2i"
    assert payload["args"][payload["args"].index("--prompt") + 1] == "A landscape"
    assert payload["args"][payload["args"].index("--device") + 1] == "cuda:7"
    assert script.read_text() == source


@pytest.mark.parametrize("mode", ["img2img", "recompose", "upscale"])
def test_runner_rejects_prompt_only_profile_for_identity_and_upscale_modes(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_PHOTO_PYTHON", "/python")
    monkeypatch.setenv("AI_STATION_PHOTO_SCRIPT", "/photo.py")
    clear_settings_cache()
    monkeypatch.setattr(module, "collect", lambda _: {"gpus": [{"index": 7}]})
    run_id = str(uuid4())
    with TestClient(module.app) as client:
        response = client.post(
            "/v1/runs/photo",
            json={
                "run_id": run_id,
                "mode": mode,
                "prompt_style": "prompt",
                "prompt": "A scene",
                "gpu": "7",
                "output_relative": f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.png",
            },
        )
        assert response.status_code == 422, response.text
    clear_settings_cache()


@pytest.mark.parametrize("mode", ["t2i", "img2img", "recompose"])
def test_prompt_wrapper_recovery_and_cancellation_own_only_its_process_group(tmp_path, mode):
    import subprocess
    import sys
    import time

    from ai_station_runner.processes import ProcessManager

    script = tmp_path / "pipeline.py"
    source = """import subprocess,sys,time
PHOTO_SUFFIX='portrait'
T2I_NEGATIVE='painting'
IDENTITY_PREFIX='preserve facial details'
RECOMPOSE_PREFIX_SINGLE='redesign portrait'
RECOMPOSE_PREFIX_MULTI='same person'
def main():
    subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
    print('ready',flush=True)
    time.sleep(30)
if __name__=='__main__':main()
"""
    script.write_text(source)
    argv = build_photo_argv(
        sys.executable,
        str(script),
        mode=mode,
        backend="qwen",
        prompt="forest",
        negative=None,
        edit_prompt="Change the wall to red",
        width=1280,
        height=704,
        steps=35,
        cfg=5,
        seed=None,
        max_side=None,
        repeats=None,
        device="cuda:7",
        output=str(tmp_path / "out.png"),
        inputs=[] if mode == "t2i" else [str(tmp_path / "source.png")],
        prompt_style="prompt" if mode == "t2i" else "instruction",
    )
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    run_id = str(uuid4())
    try:
        manager.start(run_id=run_id, argv=argv, cwd=tmp_path, executor="photo_pipe")
        deadline = time.monotonic() + 3
        while "ready" not in manager.inspect(run_id)["stdout"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        restarted = ProcessManager(tmp_path, grace_seconds=0.05)
        assert restarted.inspect(run_id)["alive"]
        assert restarted.cancel(run_id)["status"] == "canceled"
        assert not restarted.inspect(run_id)["alive"]
        assert unrelated.poll() is None
        assert script.read_text() == source
    finally:
        manager.shutdown()
        unrelated.terminate()
        unrelated.wait()


@pytest.mark.parametrize("mode", ["img2img", "recompose"])
@pytest.mark.parametrize("profile", ["pipeline", "instruction"])
def test_instruction_profile_retains_exact_user_instruction_without_portrait_injection(
    tmp_path, mode, profile
):
    import json
    import subprocess
    import sys

    script = tmp_path / "trusted_pipeline.py"
    source = """import json,sys
PHOTO_SUFFIX='pores, fine skin, DSLR'
IDENTITY_PREFIX='preserve every facial detail'
RECOMPOSE_PREFIX_SINGLE='free pose, scene, clothing, main person'
RECOMPOSE_PREFIX_MULTI='all references show the same person'
def main():
 print(json.dumps({'argv':sys.argv[1:],'suffix':PHOTO_SUFFIX,'identity':IDENTITY_PREFIX,'single':RECOMPOSE_PREFIX_SINGLE,'multi':RECOMPOSE_PREFIX_MULTI}))
if __name__=='__main__':main()
"""
    script.write_text(source)
    instruction = "Change the blue wall to solid red; keep the chair unchanged."
    argv = build_photo_argv(
        sys.executable,
        str(script),
        mode=mode,
        backend="qwen",
        prompt=instruction,
        negative=None,
        edit_prompt=instruction,
        width=832,
        height=1216,
        steps=30,
        cfg=6,
        seed=None,
        max_side=1216,
        repeats=None,
        device="cuda:7",
        output=str(tmp_path / "out.png"),
        inputs=[str(tmp_path / "source.png")],
        prompt_style=profile,
    )
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout.splitlines()[-1])
    flag = "--edit-prompt" if mode == "img2img" else "--prompt"
    assert data["argv"][data["argv"].index(flag) + 1] == instruction
    assert script.read_text() == source
    if profile == "instruction":
        assert (
            (data["identity"] == "")
            if mode == "img2img"
            else (data["suffix"] == data["single"] == data["multi"] == "")
        )
    else:
        assert all(data[key] for key in ["identity", "suffix", "single", "multi"])
