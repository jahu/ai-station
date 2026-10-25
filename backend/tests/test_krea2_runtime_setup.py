import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/install-krea2-runtime.py"
spec = importlib.util.spec_from_file_location("krea2_runtime_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_runtime_plan_neither_fetches_nor_changes_system(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected execution"))
    destination = tmp_path / "missing/runtime"
    plan = setup.plan(destination)
    assert plan["inference_qualified"] is False
    assert plan["profile"] == "gpu-only"
    assert len(plan["sources"]) == 3
    assert len(plan["dependency_lock_sha256"]) == 64
    assert not destination.parent.exists()


def test_runtime_setup_preserves_unknown_existing_directory(tmp_path, monkeypatch):
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep").write_text("external ComfyUI")
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected execution"))
    with pytest.raises(ValueError, match="Existing directory"):
        setup.install(destination)
    assert (destination / "keep").read_text() == "external ComfyUI"


def test_reinstall_rejects_modified_tracked_source_before_package_install(tmp_path, monkeypatch):
    destination = tmp_path / "owned"
    destination.mkdir()
    details = setup.plan(destination)
    (destination / setup.OWNER).write_text(json.dumps(details))
    for name in details["sources"]:
        (destination / name).mkdir()
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected execution"))
    monkeypatch.setattr(
        setup.subprocess,
        "check_output",
        lambda argv, **kw: details["sources"]["comfy"]["revision"] if "rev-parse" in argv else " M nodes.py",
    )
    with pytest.raises(ValueError, match="changed runtime"):
        setup.install(destination)


def test_runtime_setup_refuses_symlink_destination(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlinks"):
        setup.plan(link / "runtime")
