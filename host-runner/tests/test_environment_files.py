"""Offline build tools must not create conflicting runtime dependency locks."""

from pathlib import Path

import pytest
from ai_station_runner.environment_files import install_python


@pytest.mark.parametrize("with_builder", [True, False])
def test_distinct_build_tool_version_never_leaks_into_runtime_lock(tmp_path, with_builder):
    wheels = [
        dict(name="setuptools", version="78.1.0", filename="setuptools-runtime.whl", sha256="a" * 64),
        dict(
            name="setuptools",
            version="79.0.1",
            filename="setuptools-build.whl",
            sha256="b" * 64,
            build_tool=True,
            build_only=True,
        ),
    ]
    frozen = {
        "inputs": [{"kind": "python", "filename": "python.tar"}, *[dict(kind="wheel", **v) for v in wheels]]
    }
    folder = tmp_path / "environment"
    folder.mkdir()
    (folder / "wheels").mkdir()
    objects = {}
    for item in frozen["inputs"]:
        path = tmp_path / item["filename"]
        path.write_bytes(b"synthetic input; never executed")
        objects[item["filename"]] = path
    calls = []

    def builder(python):
        assert python == str(folder / "venv/bin/python")
        assert all((folder / "wheels" / v["filename"]).resolve() == objects[v["filename"]] for v in wheels)
        return [dict(name="derived", version="1.0", sha256="c" * 64)]

    arguments = dict(
        check=lambda: None,
        progress=lambda _: None,
        run_command=lambda argv, **kwargs: calls.append(argv),
        unpack=lambda *args: Path("fixed-python"),
    )
    if not with_builder:
        with pytest.raises(ValueError, match="fixed preparation callback"):
            install_python(folder, frozen, objects, **arguments)
        assert not (folder / "requirements.lock").exists()
        assert not any("install" in argv for argv in calls)
        return
    install_python(folder, frozen, objects, prepare_wheels=builder, **arguments)
    locked = (folder / "requirements.lock").read_text()
    assert "setuptools==78.1.0 --hash=sha256:" + "a" * 64 in locked
    assert "79.0.1" not in locked and "b" * 64 not in locked
    assert "derived==1.0 --hash=sha256:" + "c" * 64 in locked
    assert calls[-1][-2:] == ["pip", "check"]
