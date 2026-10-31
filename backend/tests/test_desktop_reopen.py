"""Desktop clicks reuse the live owner's private link without another startup."""

import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import Mock

import desktop
import pytest
from test_desktop_package import fixture_bundle


@pytest.fixture
def shell(tmp_path, monkeypatch):
    package, root = tmp_path / "package", tmp_path / "private"
    fixture_bundle(package)
    root.mkdir(mode=0o700)
    monkeypatch.setattr(desktop, "ROOT", package)
    monkeypatch.setattr(desktop, "state_root", lambda: root)
    monkeypatch.setattr(desktop.signal, "signal", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["desktop.py", "--console"])
    browser, prerequisites, supervise = Mock(), Mock(), Mock()
    monkeypatch.setattr(desktop.webbrowser, "open", browser)
    monkeypatch.setattr(desktop, "prerequisites", prerequisites)
    monkeypatch.setattr(desktop, "supervise", supervise)
    previous = os.umask(0o077)
    try:
        yield root, browser, prerequisites, supervise
    finally:
        os.umask(previous)


@contextmanager
def live_owner(root):
    # Real independent process/file lock; no Docker, models or UI processes.
    code = (
        "import fcntl,sys;f=open(sys.argv[1],'a');"
        "fcntl.flock(f,fcntl.LOCK_EX);print('locked',flush=True);sys.stdin.read()"
    )
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", code, str(root / "desktop.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        yield proc
    finally:
        proc.communicate(timeout=5)
        assert proc.returncode == 0


@pytest.mark.parametrize("console", [False, True])
def test_second_desktop_click_reopens_live_owner_without_starting_or_stopping_services(
    shell, monkeypatch, capsys, console
):
    root, browser, prerequisites, supervise = shell
    monkeypatch.setattr(sys, "argv", ["desktop.py", *(["--console"] if console else [])])
    monkeypatch.setattr(desktop.shutil, "which", lambda _: "/usr/bin/zenity")
    original = "http://127.0.0.1:8766/#/?setup_token=" + "a" * 43
    expected = original.replace("/#/?", "/#/setup/models?")
    with live_owner(root) as proc:
        desktop.publish_ready(root, original)
        before = (root / desktop.READY_FILE).read_bytes()
        desktop.main()
        if console:
            browser.assert_not_called()
            assert capsys.readouterr().out == desktop.READY + json.dumps({"url": expected}) + "\n"
        else:
            browser.assert_called_once_with(expected)
        assert proc.poll() is None
        assert (root / desktop.READY_FILE).read_bytes() == before
    prerequisites.assert_not_called()
    supervise.assert_not_called()
    assert not (root / "desktop.env").exists()


def test_second_click_during_startup_keeps_the_live_owner_and_explains_wait(shell, capsys):
    root, browser, prerequisites, supervise = shell
    with live_owner(root) as proc:
        desktop.main()
        assert proc.poll() is None
    assert "still starting" in capsys.readouterr().out
    browser.assert_not_called()
    prerequisites.assert_not_called()
    supervise.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_new_owner_discards_stale_link_and_removes_its_own_link_on_stop(shell, monkeypatch, fails):
    root, browser, prerequisites, _ = shell
    desktop.publish_ready(root, "http://127.0.0.1:8860")
    prerequisites.side_effect = lambda: not (root / desktop.READY_FILE).exists() or pytest.fail("Stale link")
    monkeypatch.setattr(desktop, "install_copy", lambda *args: desktop.ROOT)
    monkeypatch.setattr(desktop, "import_image", lambda *args: None)

    def supervise(*args, on_ready_url, **kwargs):
        on_ready_url("http://127.0.0.1:8766")
        assert json.loads((root / desktop.READY_FILE).read_text()) == {"url": "http://127.0.0.1:8766"}
        if fails:
            raise RuntimeError("Owned supervisor ended")

    monkeypatch.setattr(desktop, "supervise", supervise)
    if fails:
        with pytest.raises(RuntimeError, match="Owned supervisor"):
            desktop.main()
    else:
        desktop.main()
    assert not (root / desktop.READY_FILE).exists()
    browser.assert_not_called()
    with (root / "desktop.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "fifo", "oversize"])
def test_reopen_never_reads_unsafe_private_handoff_files(tmp_path, monkeypatch, kind):
    path = tmp_path / desktop.READY_FILE
    outside = tmp_path / "outside"
    outside.write_text('{"url":"http://127.0.0.1:8766"}')
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, path)
    elif kind == "fifo":
        os.mkfifo(path, mode=0o600)
    else:
        path.write_text(outside.read_text() if kind == "public" else "x" * 4097)
        path.chmod(0o644 if kind == "public" else 0o600)
    browser = Mock()
    monkeypatch.setattr(desktop.webbrowser, "open", browser)
    with pytest.raises((ValueError, OSError)):
        desktop.reopen(tmp_path)
    browser.assert_not_called()
    assert outside.read_text() == '{"url":"http://127.0.0.1:8766"}'


@pytest.mark.parametrize("url", ["https://example.com", "http://127.0.0.1:8766/#/unexpected"])
def test_unexpected_addresses_are_not_published_or_opened(tmp_path, monkeypatch, url):
    with pytest.raises(ValueError):
        desktop.publish_ready(tmp_path, url)
    assert not (tmp_path / desktop.READY_FILE).exists()
    path = tmp_path / desktop.READY_FILE
    path.write_text(json.dumps({"url": url}))
    path.chmod(0o600)
    browser = Mock()
    monkeypatch.setattr(desktop.webbrowser, "open", browser)
    with pytest.raises(ValueError):
        desktop.reopen(tmp_path)
    browser.assert_not_called()


def test_setup_handoff_is_private_and_url_validation_is_idempotent(tmp_path):
    raw = "http://127.0.0.1:8766/#/?setup_token=" + "b" * 43
    url = desktop.browser_url(raw)
    assert desktop.browser_url(url) == url
    desktop.publish_ready(tmp_path, url)
    path = tmp_path / desktop.READY_FILE
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == {"url": url}
