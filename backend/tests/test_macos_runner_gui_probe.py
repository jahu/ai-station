"""The native-only diagnostic must not start services on ordinary machines."""

import ast
import re

import macos_runner_gui_probe as probe
import pytest


def test_ordinary_host_is_refused_before_files_or_native_processes(monkeypatch):
    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **kw: pytest.fail("Started a real process"))
    monkeypatch.setattr(
        probe.tempfile, "TemporaryDirectory", lambda *a, **kw: pytest.fail("Created native state")
    )
    with pytest.raises(ValueError, match="explicit native public Mac"):
        probe.main()


def test_fixed_fixture_is_valid_python_and_profiles_the_real_installed_entry():
    source = probe.CHILD.replace("__STATE__", repr("/private/tmp/synthetic"))
    ast.parse(source)
    assert "'ai_station_runner.main'" in source
    assert "'importtime'" in source
    assert "time.monotonic()-started<20" in source
    patterns = [
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "findall"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    profile = next(pattern for pattern in patterns if pattern.startswith("^import time:"))
    assert re.findall(profile, "import time:       13 |        472 | ai_station_runner.app", re.M) == [
        ("13", "472", "ai_station_runner.app")
    ]
