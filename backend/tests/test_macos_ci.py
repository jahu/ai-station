"""Cost/permission boundaries for explicitly dispatched native Mac checks."""

import re
from pathlib import Path

import pytest
import yaml


def test_native_mac_job_is_owner_manual_public_only_on_standard_free_labels():
    value = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text())
    trigger = value.get("on", value.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    job = value["jobs"]["macos-native"]
    assert (
        job["if"]
        == "(inputs.operation == 'macos-native-checks' || inputs.operation == 'macos-native-inference') && github.event.repository.private == false && github.actor == github.repository_owner"
    )
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["matrix"]["include"] == [
        {"os": "macos-15", "architecture": "arm64"},
        {"os": "macos-15-intel", "architecture": "x86_64"},
    ]
    assert value["permissions"] == {"contents": "read"} and job["timeout-minutes"] <= 20
    assert not any("upload-artifact" in step.get("uses", "") for step in job["steps"])
    assert job["steps"][0]["with"]["persist-credentials"] is False
    inference = job["steps"][-1]
    assert inference["if"] == "inputs.operation == 'macos-native-inference'"
    assert "--run-native-inference" in inference["run"]
    assert inference["run"].startswith(
        ".native-mac/python/bin/python3.12 -IB scripts/macos_package_import_probe.py "
    )
    assert inference["env"] == {"TARGET_ARCHITECTURE": "${{ matrix.architecture }}"}
    imports = next(
        step
        for step in job["steps"]
        if step.get("name") == "Execute the actual bundled interpreter and native dependencies"
    )
    assert imports["if"] == "inputs.operation == 'macos-native-checks'"
    assert "--run-native-inference" not in imports["run"]
    installed = next(
        step
        for step in job["steps"]
        if step.get("name") == "Execute installed Runner with exact bundled interpreter"
    )
    assert (
        installed["run"]
        == '.native-mac/application-python/bin/python3.12 -IB scripts/macos_application_probe.py "$TARGET_ARCHITECTURE"'
    )
    application_build = next(
        step for step in job["steps"] if step.get("name") == "Assemble regular installed Host Runner layer"
    )
    assert "--allow-dirty" not in application_build["run"]
    assert "scripts/macos_application_python.py" in application_build["run"]
    for name in ("python", "windows-contracts", "frontend", "docker"):
        assert value["jobs"][name]["if"] == "inputs.operation == 'checks'"


def test_import_probe_cannot_run_target_acceptance_on_linux(monkeypatch):
    import macos_package_import_probe as probe

    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(probe.sys, "argv", ["probe", "arm64"])
    with pytest.raises(RuntimeError, match="native Mac"):
        probe.main()


def test_native_builder_pin_is_a_valid_two_architecture_hash_lock():
    root = Path(__file__).resolve().parents[2]
    lines = (root / "packaging/macos/build-tools.lock").read_text().splitlines()
    assert len(lines) == 4 and lines[1] == "uv==0.12.16 " + chr(92)
    assert lines[2].startswith("    --hash=sha256:") and lines[2].endswith(chr(92))
    assert lines[3].startswith("    --hash=sha256:") and not lines[3].endswith(chr(92))


def test_native_check_hashes_preserve_the_existing_developer_versions():
    root = Path(__file__).resolve().parents[2]

    def versions(path):
        return dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", path.read_text(), re.MULTILINE))

    reference = versions(root / "requirements-dev.lock")
    native = versions(root / "packaging/macos/checks.lock")
    assert all(reference[name] == version for name, version in native.items())
    assert {"pytest", "pytest-asyncio", "av", "numpy", "fastapi", "httpx"} <= set(native)
    assert "onnxruntime" not in native  # Optional Linux media QA is not the native Runner stack.
    text = (root / "packaging/macos/checks.lock").read_text()
    assert "--hash=sha256:" in text
