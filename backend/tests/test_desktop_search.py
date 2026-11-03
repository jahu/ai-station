"""Fixed image preparation; ordinary checks never contact a daemon or registry."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import desktop
import desktop_search as search
import pytest
from test_desktop_reopen import shell as shell


def engine():
    return SimpleNamespace(
        identity=("/fixed/docker", "unix:///fixed/desktop.sock"),
        environment={"HOME": "/synthetic"},
        command=lambda *args: ["/fixed/docker", "--host", "unix:///fixed/desktop.sock", *args],
    )


def test_fixed_search_digest_matches_canonical_compose():
    source = Path(__file__).resolve().parents[2] / "compose.yaml"
    assert "image: " + search.IMAGE in source.read_text()


@pytest.mark.parametrize("cached", [True, False])
def test_linux_and_windows_guest_prepare_fixed_component_before_start(monkeypatch, cached):
    selected = engine()
    selected.identity = None
    selected.command = lambda *args: ["docker", *args]
    monkeypatch.setattr(search.platform, "system", lambda: "Linux")
    monkeypatch.setattr(search.platform, "machine", lambda: "x86_64")
    metadata = SimpleNamespace(returncode=0, stdout='{"os":"linux","arch":"amd64"}')
    inspect = Mock(side_effect=[metadata] if cached else [SimpleNamespace(returncode=1), metadata])
    monkeypatch.setattr(search.subprocess, "run", inspect)
    pull = Mock(return_value=SimpleNamespace(poll=lambda: 0, returncode=0))
    monkeypatch.setattr(search.subprocess, "Popen", pull)
    assert search.prepare(selected, {}, io.StringIO(), stage=lambda _: None)
    assert inspect.call_count == (1 if cached else 2)
    if cached:
        pull.assert_not_called()
    else:
        assert pull.call_args.args[0] == [
            "docker",
            "image",
            "pull",
            "--platform",
            "linux/amd64",
            search.IMAGE,
        ]


@pytest.mark.parametrize("prepared", [True, False])
def test_linux_launcher_does_not_start_services_until_search_is_prepared(shell, monkeypatch, prepared):
    import sys

    root, _, _, _ = shell
    stages = []
    monkeypatch.setattr(sys, "argv", ["desktop.py", "--console"])
    monkeypatch.setattr(desktop, "install_copy", lambda *args: desktop.ROOT)
    monkeypatch.setattr(desktop, "import_image", lambda *a, **kw: stages.append("image"))

    def prepare(*args, canceled, **kwargs):
        assert stages == ["image"] and not canceled()
        stages.append("search")
        return prepared

    monkeypatch.setattr(search, "prepare", prepare)
    monkeypatch.setattr(desktop, "supervise", lambda *a, **kw: stages.append("services"))
    desktop.main()
    assert stages == (["image", "search", "services"] if prepared else ["image", "search"])
    assert not (root / desktop.READY_FILE).exists()


def test_linux_producer_includes_search_preparation_without_a_mac_dependency():
    from build_linux_package import SOURCE

    assert "scripts/desktop_search.py" in SOURCE


@pytest.mark.parametrize("architecture,expected", [("x86_64", "amd64"), ("arm64", "arm64")])
def test_verified_cached_component_uses_pinned_engine_without_network(monkeypatch, architecture, expected):
    inspect = Mock(
        return_value=SimpleNamespace(returncode=0, stdout=json.dumps({"os": "linux", "arch": expected}))
    )
    monkeypatch.setattr(search.subprocess, "run", inspect)
    monkeypatch.setattr(
        search.subprocess, "Popen", lambda *a, **k: pytest.fail("Downloaded a cached component")
    )
    stages = []
    assert search.prepare(engine(), {"architecture": architecture}, io.StringIO(), stage=stages.append)
    assert stages == ["Checking the local web-search component…"]
    assert inspect.call_args.args[0] == engine().command(
        "image", "inspect", search.IMAGE, "--format", search.FORMAT
    )
    assert inspect.call_args.kwargs["env"] == engine().environment


@pytest.mark.parametrize("metadata", [{"os": "windows", "arch": "amd64"}, {"os": "linux", "arch": "arm64"}])
def test_wrong_platform_is_refused_without_repull_or_start(monkeypatch, metadata):
    monkeypatch.setattr(
        search.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(metadata))
    )
    monkeypatch.setattr(
        search.subprocess, "Popen", lambda *a, **k: pytest.fail("Replaced a wrong-platform cache")
    )
    with pytest.raises(ValueError, match="platform"):
        search.prepare(engine(), {"architecture": "x86_64"}, io.StringIO(), stage=lambda _: None)


def test_fresh_component_pulls_only_fixed_digest_and_rechecks_before_services(monkeypatch, tmp_path):
    calls, stages = [], []
    inspect = Mock(
        side_effect=[
            SimpleNamespace(returncode=1),
            SimpleNamespace(returncode=0, stdout='{"os":"linux","arch":"amd64"}'),
        ]
    )
    monkeypatch.setattr(search.subprocess, "run", inspect)

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(poll=lambda: 0, returncode=0)

    monkeypatch.setattr(search.subprocess, "Popen", spawn)
    with (tmp_path / "private.log").open("w") as log:
        assert search.prepare(engine(), {"architecture": "x86_64"}, log, stage=stages.append)
    assert inspect.call_count == 2
    assert calls[0][0] == engine().command("image", "pull", "--platform", "linux/amd64", search.IMAGE)
    assert calls[0][1]["stdin"] == subprocess.DEVNULL and calls[0][1]["start_new_session"] is True
    assert "Downloading" in stages[-1]


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_cancellation_or_deadline_reaps_only_its_real_owned_download_child(monkeypatch, tmp_path, stop):
    marker = tmp_path / "owned.pid"
    script = tmp_path / "synthetic.py"
    script.write_text(
        "import os,sys,time\nfrom pathlib import Path\nif 'inspect' in sys.argv:sys.exit(1)\nPath(sys.argv[1]).write_text(str(os.getpid()))\ntime.sleep(60)\n"
    )
    selected = engine()
    selected.environment = dict(os.environ)
    selected.command = lambda *args: [sys.executable, str(script), str(marker), *args]
    children = []
    original = search.subprocess.Popen

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        if "pull" in args[0]:
            children.append(child)
        return child

    monkeypatch.setattr(search.subprocess, "Popen", spawn)
    if stop == "timeout":
        clock = iter([0, 601])
        monkeypatch.setattr(search.time, "monotonic", lambda: next(clock, 601))
    with (tmp_path / "private.log").open("w") as log:
        if stop == "cancel":
            assert not search.prepare(
                selected, {"architecture": "x86_64"}, log, stage=lambda _: None, canceled=marker.exists
            )
        else:
            with pytest.raises(TimeoutError):
                search.prepare(selected, {"architecture": "x86_64"}, log, stage=lambda _: None)
    assert len(children) == 1 and children[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)


@pytest.mark.parametrize("exit_code", [17, 0])
def test_failed_or_unverified_download_never_reports_ready(monkeypatch, tmp_path, exit_code):
    monkeypatch.setattr(search.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(
        search.subprocess,
        "Popen",
        lambda *a, **k: SimpleNamespace(poll=lambda: exit_code, returncode=exit_code),
    )
    with (tmp_path / "private.log").open("w") as log, pytest.raises(RuntimeError):
        search.prepare(engine(), {"architecture": "x86_64"}, log, stage=lambda _: None)


def test_stop_before_preparation_performs_no_engine_operation(monkeypatch):
    monkeypatch.setattr(search.subprocess, "run", lambda *a, **k: pytest.fail("Prepared after Stop"))
    assert not search.prepare(
        engine(), {"architecture": "x86_64"}, io.StringIO(), stage=lambda _: None, canceled=lambda: True
    )


def test_native_progress_offers_cancel_only_during_interruptible_download(monkeypatch):
    import macos_desktop_ui

    window = SimpleNamespace(update=Mock(), canceled=Mock(return_value=True), close=Mock())
    monkeypatch.setattr(desktop.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(macos_desktop_ui, "Preparation", lambda *a, **kw: window)
    progress = desktop.Preparation(False, cancelable=True)
    progress.stage("Preparing the bundled application image…")
    assert window.update.call_args.kwargs["cancelable"] is False
    progress.stage("Downloading the web-search component. This only happens once…")
    assert window.update.call_args.kwargs["cancelable"] is True
    assert progress.canceled()
    progress.stage("Starting your local AI Station…")
    assert window.update.call_args.kwargs["cancelable"] is False
    progress.close()
    window.close.assert_called_once()
