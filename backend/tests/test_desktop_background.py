"""Window close/background and explicit stop preserve the owned supervisor."""

import io
import json
import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import desktop
import pytest
from desktop_control import DesktopControl
from test_desktop_reopen import live_owner
from test_desktop_reopen import shell as shell


@pytest.mark.parametrize("code,text,expected", [(1, "", "background"), (1, "Stop AI Station\n", "stop")])
def test_window_close_keeps_running_and_only_explicit_stop_stops(monkeypatch, code, text, expected):
    window = Mock(returncode=code)
    window.poll.return_value = code
    window.communicate.return_value = (text, None)
    spawn = Mock(return_value=window)
    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    assert desktop.running_window("http://127.0.0.1:8766", active=lambda: True) == expected
    args = spawn.call_args.args[0]
    assert "--cancel-label=Run in background" in args and "--extra-button=Stop AI Station" in args
    window.terminate.assert_not_called()


@pytest.mark.parametrize("console,background", [(False, False), (False, True), (True, False)])
def test_background_retains_supervisor_until_its_own_stop_event(tmp_path, monkeypatch, console, background):
    proc = Mock()
    proc.stdout = io.StringIO(desktop.READY + json.dumps({"url": "http://127.0.0.1:8766"}) + "\n")
    state = {"alive": True}
    proc.poll.side_effect = lambda: None if state["alive"] else 0
    proc.terminate.side_effect = lambda: state.update(alive=False)
    monkeypatch.setattr(desktop.subprocess, "Popen", Mock(return_value=proc))
    window = Mock(return_value="background")
    monkeypatch.setattr(desktop, "running_window", window)
    browser = Mock()
    monkeypatch.setattr(desktop.webbrowser, "open", browser)
    control = SimpleNamespace(
        ready=threading.Event(), background=threading.Event(), stop_requested=threading.Event()
    )
    errors = []

    def supervise():
        try:
            desktop.supervise(
                tmp_path,
                tmp_path / "config",
                {"image_tag": "owned"},
                io.StringIO(),
                console=console,
                background=background,
                control=control,
            )
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=supervise)
    thread.start()
    try:
        assert control.background.wait(3) and control.ready.is_set()
        assert thread.is_alive() and not errors
        proc.terminate.assert_not_called()
        if console or background:
            window.assert_not_called()
        else:
            window.assert_called_once()
    finally:
        control.stop_requested.set()
        thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert not control.ready.is_set()
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=45)


def test_control_stop_during_startup_does_not_wait_for_readiness_deadline(tmp_path, monkeypatch):
    read, write = os.pipe()
    source, output = os.fdopen(read), os.fdopen(write, "w")
    proc = Mock(stdout=source)
    alive, started = threading.Event(), threading.Event()
    alive.set()
    proc.poll.side_effect = lambda: None if alive.is_set() else 0

    def terminate():
        alive.clear()
        output.close()  # The owned child's stdout ends on termination.

    proc.terminate.side_effect = terminate

    def spawn(*args, **kwargs):
        started.set()
        return proc

    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    ready = Mock()
    errors = []
    with DesktopControl(tmp_path) as control:

        def supervise():
            try:
                desktop.supervise(
                    tmp_path,
                    tmp_path / "config",
                    {"image_tag": "owned"},
                    io.StringIO(),
                    console=True,
                    control=control,
                    on_ready=ready,
                )
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=supervise)
        thread.start()
        try:
            assert started.wait(3)
            desktop.control_request(tmp_path, "stop", instance_id=control.instance_id)
            thread.join(timeout=3)
            assert not thread.is_alive() and not errors
            assert not control.ready.is_set()
            ready.assert_not_called()
            proc.terminate.assert_called_once()
        finally:
            control.stop_requested.set()
            output.close()
            thread.join(timeout=5)
            source.close()


@pytest.mark.parametrize("operation", ["--status", "--stop"])
def test_terminal_actions_never_start_an_absent_station(shell, monkeypatch, capsys, operation):
    root, browser, prerequisites, supervise = shell
    monkeypatch.setattr(sys, "argv", ["desktop.py", operation])
    desktop.main()
    assert json.loads(capsys.readouterr().out) == {"running": False}
    assert not (root / "desktop.env").exists()
    browser.assert_not_called()
    prerequisites.assert_not_called()
    supervise.assert_not_called()


def test_terminal_status_and_stop_address_only_live_desktop_owner(shell, monkeypatch, capsys):
    root, browser, prerequisites, supervise = shell
    with live_owner(root), DesktopControl(root) as owner:
        owner.ready.set()
        owner.background.set()
        monkeypatch.setattr(sys, "argv", ["desktop.py", "--status"])
        desktop.main()
        status = json.loads(capsys.readouterr().out)
        assert status == {"running": True, **owner.status()}
        monkeypatch.setattr(sys, "argv", ["desktop.py", "--stop"])
        desktop.main()
        assert json.loads(capsys.readouterr().out)["accepted"]
        assert owner.stop_requested.is_set()
    browser.assert_not_called()
    prerequisites.assert_not_called()
    supervise.assert_not_called()


@pytest.mark.parametrize("background", [False, True])
def test_reopening_with_background_flag_never_opens_native_controls(shell, monkeypatch, background):
    root, browser, prerequisites, supervise = shell
    desktop.publish_ready(root, "http://127.0.0.1:8766")
    manager = Mock()
    monkeypatch.setattr(desktop, "existing_controls", manager)
    monkeypatch.setattr(sys, "argv", ["desktop.py", *(["--background"] if background else [])])
    with live_owner(root):
        desktop.main()
    browser.assert_called_once_with("http://127.0.0.1:8766")
    assert manager.call_count == (0 if background else 1)
    prerequisites.assert_not_called()
    supervise.assert_not_called()


def test_reopened_controls_cannot_stop_replacement_instance(shell, monkeypatch):
    root, _, _, _ = shell
    desktop.publish_ready(root, "http://127.0.0.1:8766")
    previous = DesktopControl(root).__enter__()
    previous.ready.set()
    previous.background.set()
    replacement = DesktopControl(root)

    def window(url, *, active):
        assert active()
        previous.close()
        replacement.__enter__()
        assert not active()
        return "stop"  # A stale window action must be rejected independently.

    monkeypatch.setattr(desktop, "running_window", window)
    try:
        with pytest.raises(ValueError, match="instance changed"):
            desktop.existing_controls(root)
        assert not replacement.stop_requested.is_set()
    finally:
        previous.close()
        replacement.close()
