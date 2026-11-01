"""Presentation protocol tests use neutral bytes/fake children, no native dialogs."""

import hashlib
import io
import json
from types import SimpleNamespace

import build_macos_native as native_build
import desktop
import macos_desktop_ui as ui
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
