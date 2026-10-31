"""Fixed source-build authority and reproducibility; no pip, model or GPU."""

import json
import subprocess
import sys

import pytest
from ai_station_runner import avatar_source_wheel as source


@pytest.mark.parametrize("change", [{"name": "other"}, {"version": "5.0"}, {"sha256": "0" * 64}])
def test_source_exception_cannot_select_a_different_package(tmp_path, change):
    frozen = {
        "inputs": [
            {
                "kind": "sdist",
                "name": "antlr4-python3-runtime",
                "version": "4.9.3",
                "sha256": source.SOURCE_SHA,
                "size_bytes": 117034,
                **change,
            }
        ],
        "derived_wheel": {
            "filename": "antlr4_python3_runtime-4.9.3-py3-none-any.whl",
            "sha256": source.WHEEL_SHA,
            "size_bytes": 144590,
        },
    }

    def forbidden(*args, **kwargs):
        pytest.fail("A different source must never execute")

    with pytest.raises(ValueError, match="reviewed fixed"):
        source.build("python", tmp_path, frozen, {}, check=forbidden, run_command=forbidden)


@pytest.mark.parametrize("inherited", [0o002, 0o022, 0o077])
def test_fixed_build_controls_private_modes_independently_of_parent_umask(tmp_path, inherited):
    marker = tmp_path / "wheel-mode"
    # Exercise the actual build child preamble with fake tools, rather than
    # depending on a specific Python/tool installation on normal CI machines.
    program = """
import importlib.metadata, os, pathlib, sys, types
os.umask(int(sys.argv[2]))
marker=pathlib.Path(sys.argv[1])
importlib.metadata.version=lambda name: {'setuptools':'79.0.1','wheel':'0.45.1'}[name]
sys.version_info=(3,10,21)
package=types.ModuleType('setuptools');module=types.ModuleType('setuptools.build_meta')
module.build_wheel=lambda path: marker.write_text('synthetic wheel')
sys.modules['setuptools']=package;sys.modules['setuptools.build_meta']=module
sys.argv=['build','unused-output']
exec(BUILD)
"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            "BUILD=" + json.dumps(source.BUILD) + "\n" + program,
            str(marker),
            str(inherited),
        ],
        check=True,
        capture_output=True,
    )
    assert marker.stat().st_mode & 0o777 == 0o600
    assert marker.read_text() == "synthetic wheel"
