"""A selected Qwen checkpoint changes only the owned import, never the pipeline."""

import ast
import hashlib
import json
import subprocess
import sys

import pytest
from ai_station_runner.photo import build_photo_argv


@pytest.mark.parametrize("mode", ["t2i", "img2img", "recompose"])
@pytest.mark.parametrize("classic", [False, True])
def test_selected_checkpoint_preserves_argv_source_and_requested_profile(tmp_path, mode, classic):
    script = tmp_path / "photo.py"
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[2] / "reference/photo_pipe.py").read_text())
    picker = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "pick_existing"
    )
    source = """import json,sys
from pathlib import Path
QWEN_DIFFUSION_CANDIDATES=[Path('old-model.gguf')]
PHOTO_SUFFIX='photo detail'
T2I_NEGATIVE='illustration'
IDENTITY_PREFIX='identity'
RECOMPOSE_PREFIX_SINGLE='single'
RECOMPOSE_PREFIX_MULTI='multi'
def main():
 selected=pick_existing(QWEN_DIFFUSION_CANDIDATES,'Qwen diffusion')
 print(json.dumps({'model':[str(selected)],'suffix':PHOTO_SUFFIX,'identity':IDENTITY_PREFIX,'single':RECOMPOSE_PREFIX_SINGLE,'args':sys.argv[1:]}))
if __name__=='__main__': main()
"""
    source = ast.unparse(picker) + "\n" + source
    script.write_text(source)
    model = tmp_path / "chosen.gguf"
    model.write_bytes(b"model")
    argv = build_photo_argv(
        sys.executable,
        str(script),
        mode=mode,
        backend="qwen",
        prompt="A red bicycle",
        negative=None,
        edit_prompt="Change it to blue",
        width=512,
        height=768,
        steps=8,
        cfg=6,
        seed=None,
        max_side=768,
        repeats=1,
        device="cuda:7",
        output=str(tmp_path / "out.png"),
        inputs=[] if mode == "t2i" else [str(tmp_path / "input.png")],
        prompt_style="pipeline" if classic else "prompt" if mode == "t2i" else "instruction",
        model_snapshot={"path": str(model), "size": 5, "sha256": hashlib.sha256(b"model").hexdigest()},
    )
    result = subprocess.run(argv, check=True, text=True, capture_output=True)
    actual = json.loads(result.stdout.splitlines()[-1])
    assert actual["model"] == [str(model)]
    assert actual["args"][0] == mode
    assert actual["args"][actual["args"].index("--device") + 1] == "cuda:7"
    assert script.read_text() == source
    if classic:
        assert actual["suffix"] == "photo detail"
        assert actual["identity"] == "identity"
    elif mode == "t2i":
        assert actual["suffix"] == ""
    elif mode == "img2img":
        assert actual["identity"] == ""
    else:
        assert actual["single"] == ""
        assert actual["suffix"] == ""


def test_changed_checkpoint_is_rejected_before_importing_the_external_script(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"wrong")
    script = tmp_path / "photo.py"
    marker = tmp_path / "imported"
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
    from ai_station_runner import photo_job

    result = subprocess.run(
        [
            sys.executable,
            photo_job.__file__,
            "--station-model-json",
            json.dumps({"path": str(model), "size": 5, "sha256": hashlib.sha256(b"model").hexdigest()}),
            "--station-profile",
            "pipeline",
            str(script),
            "t2i",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "SHA-256" in result.stderr
    assert not marker.exists()
