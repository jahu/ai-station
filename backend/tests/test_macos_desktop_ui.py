"""Presentation protocol tests use neutral bytes/fake children, no native dialogs."""

import hashlib
import io
import json
import plistlib
from types import SimpleNamespace

import build_macos_native as native_build
import desktop
import macos_desktop_ui as ui
import macos_native_bundle as helper_bundle
import pytest


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "package"
    (root / "bin").mkdir(parents=True)
    binary = root / "bin/ai-station-native"
    binary.write_bytes(b"neutral unit fixture, never executed")
    binary.chmod(0o755)
    (root / "desktop-manifest.json").write_text(
        json.dumps({"files": {"bin/ai-station-native": hashlib.sha256(binary.read_bytes()).hexdigest()}})
    )
    monkeypatch.setattr(ui.platform, "system", lambda: "Darwin")
    return root, binary


@pytest.fixture
def bundled_package(tmp_path, monkeypatch):
    root = tmp_path / "new-package"
    root.mkdir(mode=0o700)
    source = tmp_path / "neutral-native-fixture"
    source.write_bytes(b"neutral fixture, never executed")
    source.chmod(0o700)
    executable = helper_bundle.create(root, source)
    (root / "desktop-manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in (helper_bundle.EXECUTABLE, helper_bundle.INFO)
                }
            }
        )
    )
    monkeypatch.setattr(ui.platform, "system", lambda: "Darwin")
    return root, executable, source


def test_new_helper_has_its_own_verified_application_identity(bundled_package):
    root, executable, _ = bundled_package
    assert ui.binary(root) == executable
    info = plistlib.loads((root / helper_bundle.INFO).read_bytes())
    assert info["CFBundleIdentifier"] == "io.ai-station.presentation"
    assert info["LSUIElement"] is True
    assert info["CFBundleExecutable"] == executable.name


def test_changed_bundle_info_is_refused_before_execution(bundled_package):
    root, _, _ = bundled_package
    (root / helper_bundle.INFO).write_bytes(b"changed")
    with pytest.raises(ValueError, match="bundle changed"):
        ui.binary(root)


def test_declared_wrong_bundle_identity_still_cannot_select_a_helper(bundled_package):
    root, _, _ = bundled_package
    info = root / helper_bundle.INFO
    value = plistlib.loads(info.read_bytes())
    value["CFBundleIdentifier"] = "unrelated.application"
    info.write_bytes(plistlib.dumps(value))
    receipt = root / "desktop-manifest.json"
    value = json.loads(receipt.read_text())
    value["files"][helper_bundle.INFO] = hashlib.sha256(info.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="bundle identity changed"):
        ui.binary(root)


def test_helper_bundle_cannot_escape_through_a_parent_link(bundled_package, tmp_path):
    root, _, _ = bundled_package
    directory = root / helper_bundle.BUNDLE
    outside = tmp_path / "outside-helper"
    directory.rename(outside)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="redirected"):
        ui.binary(root)
    assert (outside / "Contents/Info.plist").exists()


def test_bundle_producer_never_overwrites_an_existing_helper(bundled_package):
    root, executable, source = bundled_package
    before = executable.read_bytes()
    source.write_bytes(b"changed build input")
    with pytest.raises(FileExistsError):
        helper_bundle.create(root, source)
    assert executable.read_bytes() == before


def test_verified_interface_is_required_before_a_dialog_can_execute(package):
    root, binary = package
    assert ui.binary(root) == binary
    binary.write_bytes(b"changed")
    with pytest.raises(ValueError, match="interface changed"):
        ui.binary(root)


def test_interface_symlink_cannot_select_an_external_executable(package, tmp_path):
    root, binary = package
    outside = tmp_path / "outside"
    outside.write_bytes(binary.read_bytes())
    outside.chmod(0o755)
    binary.unlink()
    binary.symlink_to(outside)
    with pytest.raises(ValueError, match="redirected"):
        ui.binary(root)


def test_dialog_uses_bounded_stdin_not_executable_arguments_or_application_credentials(package, monkeypatch):
    root, binary = package
    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "PRIVATE_FIXTURE_TOKEN")
    monkeypatch.setenv("GITHUB_TOKEN", "PRIVATE_FIXTURE_TOKEN")
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(ui.subprocess, "run", run)
    assert ui.dialog(root, "--question", '--text=Quotes " and\nnew lines', "--ok-label=Set up") == 1
    assert seen["argv"] == [str(binary), "--native-dialog"]
    assert json.loads(seen["input"])["text"] == 'Quotes " and\nnew lines'
    assert "AI_STATION_LLM_API_KEY" not in seen["env"] and "GITHUB_TOKEN" not in seen["env"]
    with pytest.raises(ValueError, match="bounded frame"):
        ui.payload({"text": "a" * 17000})


def test_unexpected_dialog_failure_is_not_reported_as_user_approval(package, monkeypatch):
    root, _ = package
    monkeypatch.setattr(ui.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2))
    with pytest.raises(RuntimeError, match="could not complete"):
        ui.dialog(root, "--question")


def test_backup_selection_uses_private_stdin_and_bounded_replies(package, monkeypatch):
    root, binary = package
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stdout=b'{"action":"resume"}')

    monkeypatch.setattr(ui.subprocess, "run", run)
    assert ui.backup_selection(root, pending="restore", can_abort=False) == {"action": "resume"}
    assert seen["argv"] == [str(binary), "--native-backups"]
    assert json.loads(seen["input"]) == {"pending": "restore", "can_abort": False}
    monkeypatch.setattr(
        ui.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"x" * 16385)
    )
    with pytest.raises(RuntimeError, match="could not complete"):
        ui.backup_folder(root)


def test_recovery_password_is_a_private_child_reply_never_an_argument_or_log(package, monkeypatch):
    root, binary = package
    secret = {
        "username": " Ｏｗｎｅｒ ",
        "password": "synthetic private recovery password",
        "reset_mfa": True,
    }
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps(secret).encode())

    monkeypatch.setattr(ui.subprocess, "run", run)
    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "PRIVATE_FIXTURE_TOKEN")
    result = ui.administrator_recovery(root)
    assert result == secret | {"username": "Owner"}
    assert seen["argv"] == [str(binary), "--native-admin-recovery"] and seen["input"] == b"{}\n"
    assert "AI_STATION_LLM_API_KEY" not in seen["env"]
    assert secret["password"] not in repr(seen)


def test_recovery_cancel_never_returns_partial_credentials(package, monkeypatch):
    root, _ = package
    monkeypatch.setattr(
        ui.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b'{"action":"cancel"}')
    )
    assert ui.administrator_recovery(root) is None


def test_cancelable_progress_reads_only_its_own_bounded_cancel_frame(package, monkeypatch):
    import os

    root, _ = package
    reader, writer = os.pipe()
    output = os.fdopen(reader, "rb")
    channel = io.BytesIO()
    process = SimpleNamespace(stdin=channel, stdout=output, poll=lambda: None, wait=lambda **kw: 0)
    monkeypatch.setattr(ui.subprocess, "Popen", lambda *a, **kw: process)
    progress = ui.Preparation(root, cancelable=True)
    try:
        assert not progress.canceled()
        os.write(writer, b'{"action":"cancel"}\n')
        assert progress.canceled() and progress.canceled()
        progress.update("Finishing safely", done=0, total=1, cancelable=False)
        frames = [json.loads(line) for line in channel.getvalue().splitlines()]
        assert frames[-1] == {"cancelable": False, "done": 0, "total": 1}
    finally:
        os.close(writer)
        progress.close()
    assert output.closed


def test_update_heading_uses_private_bounded_presentation_frames(package, monkeypatch):
    root, _ = package
    channel = io.BytesIO()
    process = SimpleNamespace(stdin=channel, poll=lambda: 0, wait=lambda **kw: 0)
    monkeypatch.setattr(ui.subprocess, "Popen", lambda *a, **kw: process)
    progress = ui.Preparation(root, heading="Preparing your local update")
    assert json.loads(channel.getvalue()) == {"heading": "Preparing your local update"}
    progress.close()


@pytest.mark.parametrize("action,expected", [("stop", "stop"), ("background", "background")])
def test_running_window_returns_only_selected_action_and_never_passes_readiness_token(
    package, monkeypatch, action, expected
):
    root, _ = package
    channel = io.BytesIO()
    process = SimpleNamespace(stdin=channel, poll=lambda: 0, returncode=0, wait=lambda **k: 0)
    observed = {}

    def communicate(**kwargs):
        return json.dumps({"action": action}).encode(), None

    process.communicate = communicate

    class Channel(io.BytesIO):
        def close(self):
            observed["frame"] = self.getvalue()
            super().close()

    process.stdin = Channel()
    monkeypatch.setattr(ui.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(ui.webbrowser, "open", lambda *_: pytest.fail("Unselected browser action"))
    assert (
        ui.running_window(root, "http://127.0.0.1:8765/#setup-token=PRIVATE_FIXTURE", active=lambda: True)
        == expected
    )
    assert b"PRIVATE_FIXTURE" not in observed["frame"]


def test_native_compiler_refuses_another_platform_before_creating_output(tmp_path, monkeypatch):
    monkeypatch.setattr(native_build.platform, "system", lambda: "Linux")
    output = tmp_path / "not-created"
    with pytest.raises(RuntimeError, match="actual supported Mac"):
        native_build.build(output, "arm64")
    assert not output.exists()


def test_package_check_validates_code_before_any_ui_or_data_directory(tmp_path, monkeypatch, capsys):
    import sys

    from test_desktop_package import fixture_bundle

    root = tmp_path / "bundle"
    expected = fixture_bundle(root)
    monkeypatch.setattr(desktop, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["station", "--package-check"])
    monkeypatch.setattr(
        desktop, "state_root", lambda: pytest.fail("Created station data during read-only check")
    )
    desktop.main()
    assert json.loads(capsys.readouterr().out) == {
        "package_verified": True,
        "bundle_id": expected["bundle_id"],
        "workloads_started": False,
    }
    (root / "station").write_text("tampered")
    with pytest.raises(ValueError, match="missing or changed"):
        desktop.main()


def test_failed_package_check_exits_without_opening_an_error_dialog(tmp_path, monkeypatch):
    import runpy
    import sys
    from pathlib import Path

    from test_desktop_package import fixture_bundle

    root = tmp_path / "bundle"
    fixture_bundle(root)
    script = root / "scripts/desktop.py"
    script.parent.mkdir()
    script.write_bytes(Path(desktop.__file__).read_bytes())
    (root / "station").write_text("tampered")
    monkeypatch.setattr(sys, "argv", [str(script), "--package-check"])
    monkeypatch.setattr(desktop.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ui, "dialog", lambda *_: pytest.fail("Opened UI during package check failure"))
    with pytest.raises(SystemExit, match="missing or changed"):
        runpy.run_path(str(script), run_name="__main__")
