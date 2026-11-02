"""An independent native desktop owns Stop; the updater never signals its PID."""

import fcntl
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

import desktop_update_owner as update
import pytest
import test_desktop_versions as fixtures

PACKAGE = fixtures.PACKAGE
installation = fixtures.installation

CANDIDATE = PACKAGE | {"bundle_id": "d" * 64, "version": "0.2.0", "source_epoch": 1790000001}


@contextmanager
def start(root, config, channel, *, stubborn=False):
    scripts = Path(update.__file__).parent
    code = (
        "import fcntl,json,os,signal,sys,time;from pathlib import Path;"
        f"sys.path[:0]={[str(scripts), str(scripts.parent / 'host-runner')]!r};"
        "from desktop_control import DesktopControl;from desktop_versions import begin,ready;"
        "os.umask(0o077);root,config,channel=map(Path,sys.argv[1:4]);"
        "lock=open(root/'desktop.lock','a');fcntl.flock(lock,fcntl.LOCK_EX);"
        f"package={PACKAGE!r}\n"
        "with DesktopControl(channel,package=package) as control:\n"
        " begin(root,package,config,control.instance_id);ready(root,package,config,control.instance_id)\n"
        " control.ready.set();print(control.instance_id,flush=True)\n"
        " while not control.stop_requested.wait(0.05):pass\n"
        " (root/('stop-'+control.instance_id)).write_text('requested')\n"
        f" if {stubborn!r}:time.sleep(30)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", code, str(root), str(config), str(channel)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        instance = proc.stdout.readline().strip()
        if len(instance) != 32:
            _, error = proc.communicate(timeout=3)
            pytest.fail("Neutral native owner failed to start: " + error)
        yield proc, instance
    finally:
        if proc.poll() is None:
            proc.terminate()  # Only our immediate unreaped test child.
        proc.communicate(timeout=5)


@pytest.fixture
def channel():
    parent = "/private/tmp" if sys.platform == "darwin" else None
    with tempfile.TemporaryDirectory(prefix="asu-", dir=parent) as path:
        yield Path(path).resolve()


def test_consent_stops_only_attested_owner_and_holds_native_startup_lock(installation, channel):
    root, config, data = installation
    keep = data / "keep.txt"
    keep.write_text("original data")
    seen = []
    with start(root, config, channel) as (proc, instance):

        def consent(previous, candidate):
            seen.append((previous, candidate.copy()))
            candidate["bundle_id"] = "e" * 64  # Callback cannot mutate frozen candidate.
            return True

        with update.handoff(root, config, channel, CANDIDATE, consent) as owned:
            assert owned["instance_id"] == instance and owned["data"] == data
            assert owned["candidate"] == CANDIDATE and owned["previous"] == PACKAGE
            assert (root / ("stop-" + instance)).exists()
            proc.wait(timeout=3)
            with (root / "desktop.lock").open("a") as competing:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (root / "desktop.lock").open("a") as next_owner:
            fcntl.flock(next_owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert seen == [(PACKAGE, CANDIDATE)]
    assert keep.read_text() == "original data"


@pytest.mark.parametrize("answer", [False, None, 1, "yes"])
def test_no_explicit_native_consent_never_stops_or_changes_data(installation, channel, answer):
    root, config, _ = installation
    with start(root, config, channel) as (proc, instance):
        before = (root / "desktop-version.json").read_bytes()
        with update.handoff(root, config, channel, CANDIDATE, lambda *args: answer) as result:
            assert result is None
        assert proc.poll() is None
        assert not (root / ("stop-" + instance)).exists()
        assert (root / "desktop-version.json").read_bytes() == before


def test_storage_change_during_consent_cannot_stop_an_owner(installation, channel):
    root, config, _ = installation
    with start(root, config, channel) as (proc, instance):

        def consent(*args):
            config.write_text(config.read_text().replace("ai-station-test", "different-project"))
            return True

        with pytest.raises(ValueError):
            with update.handoff(root, config, channel, CANDIDATE, consent):
                pytest.fail("Changed installation was adopted")
        assert proc.poll() is None and not (root / ("stop-" + instance)).exists()


@pytest.mark.parametrize("name", ["desktop.lock", "desktop-update.lock"])
def test_replaced_lock_during_consent_never_stops_the_owner(installation, channel, name):
    root, config, _ = installation
    with start(root, config, channel) as (proc, instance):

        def consent(*args):
            path = root / name
            path.rename(root / (name + ".original"))
            path.touch(mode=0o600)
            return True

        with pytest.raises(ValueError, match="lock identity changed"):
            with update.handoff(root, config, channel, CANDIDATE, consent):
                pytest.fail("Replacement lock was accepted")
        assert proc.poll() is None and not (root / ("stop-" + instance)).exists()


def test_replacement_owner_during_consent_is_never_sent_stop(installation, channel):
    root, config, _ = installation
    with ExitStack() as stack:
        old, old_instance = stack.enter_context(start(root, config, channel))
        replacement = []

        def consent(*args):
            update.request(channel, "stop", instance_id=old_instance)
            old.wait(timeout=3)
            replacement.append(stack.enter_context(start(root, config, channel)))
            return True

        with pytest.raises(ValueError, match="changed during update consent"):
            with update.handoff(root, config, channel, CANDIDATE, consent):
                pytest.fail("Replacement owner was accepted without new consent")
        proc, instance = replacement[0]
        assert instance != old_instance
        assert proc.poll() is None and not (root / ("stop-" + instance)).exists()


@pytest.mark.parametrize("kind", ["same", "older"])
def test_invalid_update_never_prompts_or_stops_the_owner(installation, channel, kind):
    root, config, _ = installation
    candidate = PACKAGE if kind == "same" else CANDIDATE | {"source_epoch": 1}
    with start(root, config, channel) as (proc, instance):

        def consent(*args):
            pytest.fail("An invalid update requested consent")

        with pytest.raises(ValueError):
            with update.handoff(root, config, channel, candidate, consent):
                pytest.fail("Invalid package accepted")
        assert proc.poll() is None and not (root / ("stop-" + instance)).exists()


def test_other_update_gate_refuses_before_consent_or_stop(installation, channel):
    root, config, _ = installation
    with start(root, config, channel) as (proc, instance):
        descriptor = update.lock_file(root, "desktop-update.lock", create=True)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(RuntimeError, match="already being inspected"):
                with update.handoff(root, config, channel, CANDIDATE, lambda *args: pytest.fail("consent")):
                    pytest.fail("Concurrent updater entered")
        finally:
            os.close(descriptor)
        assert proc.poll() is None and not (root / ("stop-" + instance)).exists()


def test_timeout_never_force_kills_the_owner_and_releases_update_gate(installation, channel):
    root, config, _ = installation
    with start(root, config, channel, stubborn=True) as (proc, instance):
        with pytest.raises(RuntimeError, match="still stopping"):
            with update.handoff(root, config, channel, CANDIDATE, lambda *args: True, timeout=0.1):
                pytest.fail("Live owner lock was ignored")
        assert proc.poll() is None and (root / ("stop-" + instance)).exists()
        fd = update.lock_file(root, "desktop-update.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)


@pytest.mark.parametrize("kind", ["public", "hardlink", "fifo", "symlink"])
def test_unsafe_update_locks_are_not_replaced_or_signaled(installation, channel, kind):
    root, config, _ = installation
    path = root / "desktop-update.lock"
    if kind == "fifo":
        os.mkfifo(path, mode=0o600)
    else:
        path.write_text("keep")
        path.chmod(0o600)
        if kind == "public":
            path.chmod(0o644)
        elif kind == "hardlink":
            os.link(path, root / "extra-lock")
        else:
            path.rename(root / "original-lock")
            path.symlink_to(root / "original-lock")
    before = path.lstat().st_ino
    with start(root, config, channel) as (proc, instance):
        with pytest.raises((ValueError, OSError)):
            with update.handoff(root, config, channel, CANDIDATE, lambda *args: True):
                pytest.fail("Unsafe lock accepted")
        assert proc.poll() is None and not (root / ("stop-" + instance)).exists()
    assert path.lstat().st_ino == before
