"""Execute fixed site wiring without a model, package install or network."""

import shutil
import subprocess

import pytest
from app.static_site import commands


@pytest.mark.parametrize("invalid", [None, "missing", "empty", "symlink", "hardlink", "root_symlink"])
def test_fixed_static_commands_build_real_source_or_reject_unsafe_inputs(tmp_path, invalid):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; actual managed-Node qualification remains separate")
    src = tmp_path / "src"
    src.mkdir()
    entry = src / "index.html"
    if invalid != "missing":
        entry.write_text(
            "" if invalid == "empty" else "<!doctype html><title>Example</title><h1>Real source</h1>"
        )
    (src / "style.css").write_text("body { color: navy; }")
    if invalid == "symlink":
        (src / "alias.html").symlink_to(entry)
    elif invalid == "hardlink":
        (src / "alias.html").hardlink_to(entry)
    elif invalid == "root_symlink":
        src.rename(tmp_path / "real-source")
        src.symlink_to(tmp_path / "real-source", target_is_directory=True)
    outcomes = []
    for command in commands():
        assert command["argv"][:2] == ["node", "-e"]
        result = subprocess.run([node, *command["argv"][1:]], cwd=tmp_path, capture_output=True, timeout=10)
        outcomes.append(result.returncode)
    if invalid:
        assert all(outcomes) and not (tmp_path / "dist").exists()
    else:
        assert outcomes == [0, 0]
        assert (tmp_path / "dist/index.html").read_bytes() == entry.read_bytes()
        assert (tmp_path / "dist/style.css").read_bytes() == (src / "style.css").read_bytes()
        assert not (tmp_path / "package.json").exists()
