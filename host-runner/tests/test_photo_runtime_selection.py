"""Configured native runtime selection cannot be supplied by a photo client."""

import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import app as module
from ai_station_runner.photo import PhotoCommandError, build_photo_argv
from fastapi.testclient import TestClient


def arguments(tmp_path, mode):
    return dict(
        mode=mode,
        backend="qwen",
        prompt="--station-sd-cli /untrusted",
        negative=None,
        edit_prompt="Change the cabinet's viewpoint",
        width=512,
        height=768,
        steps=30,
        cfg=6,
        seed=None,
        max_side=768,
        repeats=1,
        device="cuda:7",
        output=str(tmp_path / "result.png"),
        inputs=[] if mode == "t2i" else [str(tmp_path / "source.png")],
    )


@pytest.mark.parametrize("mode", ["t2i", "img2img", "recompose"])
@pytest.mark.parametrize("classic", [False, True])
@pytest.mark.parametrize("selected_model", [False, True])
def test_configured_engine_preserves_model_profile_and_literal_inputs(
    tmp_path, mode, classic, selected_model
):
    runtime = tmp_path / "native runtime" / "sd-cli"
    runtime.parent.mkdir()
    runtime.write_text("#!/bin/sh\nexit 0\n")
    runtime.chmod(0o700)
    script = tmp_path / "pipeline.py"
    source = """import json,sys
from pathlib import Path
SDCLI=Path('/old/sd-cli')
QWEN_DIFFUSION_CANDIDATES=[Path('old.gguf')]
PHOTO_SUFFIX='style'
T2I_NEGATIVE='negative'
IDENTITY_PREFIX='identity'
RECOMPOSE_PREFIX_SINGLE='single'
RECOMPOSE_PREFIX_MULTI='multi'
def main():
 print(json.dumps({'runtime':str(SDCLI),'models':[str(p) for p in QWEN_DIFFUSION_CANDIDATES],'argv':sys.argv[1:],'style':[PHOTO_SUFFIX,IDENTITY_PREFIX,RECOMPOSE_PREFIX_SINGLE]}))
if __name__=='__main__':main()
"""
    script.write_text(source)
    model = tmp_path / "selected.gguf"
    model.write_bytes(b"model")
    snapshot = (
        dict(path=str(model), size=5, sha256=hashlib.sha256(b"model").hexdigest()) if selected_model else None
    )
    options = arguments(tmp_path, mode)
    style = "pipeline" if classic else "prompt" if mode == "t2i" else "instruction"
    argv = build_photo_argv(
        sys.executable,
        str(script),
        **options,
        prompt_style=style,
        model_snapshot=snapshot,
        sd_cli=str(runtime),
    )
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    actual = json.loads(result.stdout.splitlines()[-1])
    assert actual["runtime"] == str(runtime)
    expected_model = str(model) if selected_model else "old.gguf"
    assert actual["models"] == [expected_model]
    assert actual["argv"][0] == mode
    flag = "--edit-prompt" if mode == "img2img" else "--prompt"
    expected_prompt = options["edit_prompt"] if mode == "img2img" else options["prompt"]
    assert actual["argv"][actual["argv"].index(flag) + 1] == expected_prompt
    if classic:
        assert actual["style"] == ["style", "identity", "single"]
    else:
        assert actual["style"][0 if mode == "t2i" else 1 if mode == "img2img" else 2] == ""
    assert script.read_text() == source
    assert runtime.read_text() == "#!/bin/sh\nexit 0\n"


def test_missing_configured_engine_does_not_fall_back_or_import_pipeline(tmp_path):
    from ai_station_runner import photo_job

    script = tmp_path / "pipeline.py"
    marker = tmp_path / "imported"
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    missing = str(tmp_path / "missing-sd-cli")
    with pytest.raises(PhotoCommandError, match="executable"):
        build_photo_argv(sys.executable, str(script), **arguments(tmp_path, "t2i"), sd_cli=missing)
    result = subprocess.run(
        [
            sys.executable,
            photo_job.__file__,
            "--station-sd-cli",
            missing,
            "--station-profile",
            "pipeline",
            str(script),
            "t2i",
        ],
        capture_output=True,
    )
    assert result.returncode != 0 and not marker.exists()


def test_only_native_configuration_selects_the_engine_and_capabilities_refuse_missing_binary(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "sd-cli"
    runtime.write_text("#!/bin/sh\nexit 0\n")
    runtime.chmod(0o700)
    pipeline = tmp_path / "pipeline.py"
    pipeline.touch()
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_PHOTO_PYTHON", sys.executable)
    monkeypatch.setenv("AI_STATION_PHOTO_SCRIPT", str(pipeline))
    monkeypatch.setenv("AI_STATION_SD_CLI", str(runtime))
    module.get_settings.cache_clear()
    calls = []

    def start(**kwargs):
        calls.append(kwargs)
        return {"run_id": kwargs["run_id"]}

    monkeypatch.setattr(module, "manager", lambda: SimpleNamespace(start=start))
    monkeypatch.setattr(module, "collect", lambda _: {"gpus": [{"index": 7}]})
    rid = str(uuid4())
    body = {
        "run_id": rid,
        "mode": "t2i",
        "prompt": "A cabinet",
        "gpu": "7",
        "output_relative": f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.png",
    }
    with TestClient(module.app) as api:
        assert api.get("/v1/photo/capabilities").json()["available"]
        response = api.post("/v1/runs/photo", json={**body, "sd_cli": "/client/chosen"})
        assert response.status_code == 422 and calls == []
        assert api.post("/v1/runs/photo", json=body).status_code == 200
        assert calls[0]["argv"][calls[0]["argv"].index("--station-sd-cli") + 1] == str(runtime)
        runtime.unlink()
        assert not api.get("/v1/photo/capabilities").json()["available"]
        assert api.post("/v1/runs/photo", json=body).status_code == 422
        assert len(calls) == 1
