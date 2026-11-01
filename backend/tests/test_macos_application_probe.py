"""Installed-package verification controls; simulated receipts are not native QA."""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import macos_application_probe as probe
import pytest


@pytest.fixture
def package(tmp_path, monkeypatch):
    root, layer = tmp_path / "repository", tmp_path / "python"
    relative = "host-runner/ai_station_runner/__init__.py"
    for path in (root / relative, layer / probe.SITE / "__init__.py", layer / "bin/python3.12"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# neutral fixture, never executed\n")
    recipe = Path(__file__).resolve().parents[2] / "packaging/macos/arm64.json"
    target = root / "packaging/macos/arm64.json"
    target.parent.mkdir(parents=True)
    frozen = json.loads(recipe.read_text())
    target.write_text(json.dumps(frozen))
    manifest_hash = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    base = {
        "schema": 1,
        "architecture": "arm64",
        "manifest_sha256": manifest_hash,
        "python_version": "3.12.14",
        "files": {"bin/python3.12": probe.digest(layer / "bin/python3.12")},
    }
    (layer / "native-python.json").write_text(json.dumps(base))
    value = {
        "schema": 1,
        "profile": "application-python312-darwin-arm64-v1",
        "architecture": "arm64",
        "source_head": "a" * 40,
        "source_dirty": False,
        "native_application_executed": False,
        "macos_installer_qualified": False,
        "base_inventory_unchanged": True,
        "base_manifest_sha256": manifest_hash,
        "base_receipt_sha256": probe.digest(layer / "native-python.json"),
        "runner_source_files": {"__init__.py": probe.digest(root / relative)},
        "files": probe.inventory(layer),
    }
    (layer / "application-python.json").write_text(json.dumps(value))

    def git(argv, *, cwd, text=False):
        assert cwd == root
        return "a" * 40 if text else (relative + "\0").encode()

    monkeypatch.setattr(probe.subprocess, "check_output", git)
    return root, layer, value


def test_exact_layer_checks_unchanged_base_and_tracked_installed_bytes(package):
    root, layer, expected = package
    value, files = probe.verify_layer(layer, "arm64", root)
    assert value == expected and "application-python.json" in files


@pytest.mark.parametrize("name", ["bin/python3.12", probe.SITE + "/__init__.py"])
def test_any_base_or_installed_code_change_refuses_before_launch(package, name):
    root, layer, _ = package
    (layer / name).write_text("tampered bytes")
    with pytest.raises(ValueError, match="inventory changed"):
        probe.verify_layer(layer, "arm64", root)


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_dirty", True),
        ("source_head", "b" * 40),
        ("native_application_executed", True),
        ("architecture", "x86_64"),
        ("base_receipt_sha256", "0" * 64),
    ],
)
def test_unreviewed_or_other_package_identity_is_not_native_acceptance(package, key, value):
    root, layer, record = package
    record[key] = value
    (layer / "application-python.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="identity differs"):
        probe.verify_layer(layer, "arm64", root)


def test_resealed_extra_runner_file_cannot_pass_as_tracked_package(package):
    root, layer, record = package
    (layer / probe.SITE / "extra.py").write_text("untracked module")
    record["files"] = probe.inventory(layer)
    record["files"].pop("application-python.json")
    (layer / "application-python.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="tracked package bytes"):
        probe.verify_layer(layer, "arm64", root)


def test_external_package_link_is_not_hashed_or_followed(package, tmp_path):
    _, layer, _ = package
    outside = tmp_path / "private-file"
    outside.write_text("PRIVATE_FIXTURE_TOKEN")
    (layer / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="link escapes"):
        probe.inventory(layer)


def test_non_native_entry_refuses_before_reading_package_or_launching(monkeypatch):
    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(probe.sys, "argv", ["probe", "arm64"])
    monkeypatch.setattr(probe, "verify_layer", lambda *a: pytest.fail("Read package on wrong platform"))
    monkeypatch.setattr(probe, "exercise_runner", lambda: pytest.fail("Launched on wrong platform"))
    with pytest.raises(RuntimeError, match="exact isolated"):
        probe.main()


def test_cleanup_escalates_only_its_immediate_child_and_reaps_it():
    class Child:
        def __init__(self):
            self.calls = []

        def poll(self):
            return None

        def terminate(self):
            self.calls.append("term")

        def wait(self, *, timeout):
            self.calls.append(("wait", timeout))
            if timeout == 15:
                raise subprocess.TimeoutExpired("owned-child", timeout)

        def kill(self):
            self.calls.append("kill")

    child = Child()
    probe.stop_child(child)
    assert child.calls == ["term", ("wait", 15), "kill", ("wait", 5)]


@pytest.mark.parametrize(
    "field,value", [("pid", True), ("pid", -1), ("pid", 2**31), ("owner_pid", 99), ("run_id", "other")]
)
def test_owner_handoff_cannot_fabricate_a_different_process_or_helper_exit(tmp_path, field, value):
    record = {"pid": 42, "owner_pid": 43, "run_id": "fixture-identity"}
    record[field] = value
    (tmp_path / "owner.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="owner exit/handoff"):
        probe.owner_handoff(tmp_path, SimpleNamespace(pid=43, returncode=0), "fixture-identity")


def test_reaped_original_helper_is_required_before_adopting_its_process(tmp_path):
    (tmp_path / "owner.json").write_text(
        json.dumps({"pid": 42, "owner_pid": 43, "run_id": "fixture-identity"})
    )
    assert (
        probe.owner_handoff(tmp_path, SimpleNamespace(pid=43, returncode=0), "fixture-identity")["pid"] == 42
    )
    with pytest.raises(ValueError, match="owner exit/handoff"):
        probe.owner_handoff(tmp_path, SimpleNamespace(pid=43, returncode=1), "fixture-identity")


def test_helper_is_also_guarded_against_non_native_invocation(tmp_path, monkeypatch):
    before = set(tmp_path.iterdir())  # Backend's shared fixture may already own a data directory.
    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="isolated native"):
        probe.fixture_owner(tmp_path, "fixture-identity")
    assert set(tmp_path.iterdir()) == before


def test_main_never_adds_source_paths_and_inventory_failure_cannot_become_success(package, monkeypatch):
    root, layer, _ = package
    monkeypatch.setattr(probe, "__file__", str(root / "scripts/probe.py"))
    monkeypatch.setattr(
        probe,
        "sys",
        SimpleNamespace(
            argv=["probe", "arm64"],
            executable=str(layer / "bin/python3.12"),
            prefix=str(layer),
            version_info=(3, 12, 14),
            flags=SimpleNamespace(isolated=1),
            dont_write_bytecode=True,
        ),
    )
    monkeypatch.setattr(probe.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(probe.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        probe.importlib.util,
        "find_spec",
        lambda _: SimpleNamespace(origin=str(layer / probe.SITE / "__init__.py")),
    )

    def execute():
        (layer / "new-cache-file").write_text("unexpected write")
        return {"normal_Runner_main_passed": True}

    monkeypatch.setattr(probe, "exercise_runner", execute)
    with pytest.raises(ValueError, match="complete application interpreter"):
        probe.main()
