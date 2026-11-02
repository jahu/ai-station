"""Native update UX/entry contracts; real private owners, neutral package/image fixtures."""

import fcntl
import json
import platform
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import desktop
import desktop_update as update
import desktop_versions as versions
import pytest
import test_desktop_versions as fixtures
from desktop_control import request
from desktop_engine import DockerEngine
from test_desktop_package import fixture_bundle
from test_desktop_update_owner import start as owner

installation = fixtures.installation


class Progress:
    def __init__(self):
        self.stages = []
        self.closed = False

    def stage(self, text):
        self.stages.append(text)

    def close(self):
        self.closed = True


@pytest.fixture
def setup(installation, tmp_path, monkeypatch):
    root, config, data = installation
    (data / "runtime").mkdir(mode=0o700)
    (data / "keep.txt").write_text("original private data")
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(platform, "mac_ver", lambda: ("15.0", (), ""))
    old = tmp_path / "original-payload"
    old_value = (
        fixture_bundle(old)
        | fixtures.PACKAGE
        | {
            "platform": "Darwin",
            "architecture": "x86_64",
            "minimum_os": "13.3",
            "desktop_protocol": desktop.DESKTOP_PROTOCOL,
        }
    )
    (old / "desktop-manifest.json").write_text(json.dumps(old_value))
    old = desktop.install_copy(root, old, old_value)
    app = tmp_path / "Downloaded AI Station.app"
    (app / "Contents").mkdir(parents=True)
    source = app / "Contents/Resources"
    value = fixture_bundle(source) | {
        key: old_value[key] for key in ("platform", "architecture", "minimum_os", "desktop_protocol")
    }
    value.update(
        bundle_id="d" * 64,
        image_id="sha256:" + "e" * 64,
        image_tag="ai-station:desktop-" + "d" * 16,
        version="0.2.0",
        source_epoch=1790000001,
    )
    (source / "desktop-manifest.json").write_text(json.dumps(value))
    progress, steps, clients, answer = Progress(), [], [], [0]
    engine = DockerEngine(
        ("/fixed/docker", "--host", "unix:///fixed.sock"), {}, ("/fixed/docker", "unix:///fixed.sock")
    )
    monkeypatch.setattr(desktop, "ROOT", old)
    monkeypatch.setattr(desktop, "state_root", lambda: root)
    monkeypatch.setattr(desktop, "Preparation", lambda *a, **kw: progress)
    monkeypatch.setattr(desktop, "select_engine", lambda env: engine)
    monkeypatch.setattr(desktop, "dialog", lambda *args: answer[0])
    monkeypatch.setattr(desktop, "import_image", lambda *a, **kw: steps.append("image"))
    monkeypatch.setattr(update, "check_bridge", lambda *a: steps.append("bridge") or True)

    class Client:
        # The real image/SQLite lifecycle has independent unit and opt-in Docker
        # coverage. This boundary observes sequencing while actual kernel Stop
        # and native desktop locks remain in use.
        def __init__(self, root, config, engine, previous, target, identity):
            clients.append(self)
            self.root, self.config, self.target, self.identity = root, config, target, identity
            assert versions.package_identity(previous) == fixtures.PACKAGE
            with (root / "desktop.lock").open("a") as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def state(self):
            return {"current": None, "final": None}

        def run(self, action):
            steps.append(action)
            return {"phase": {"prepare": "prepared", "status": "prepared", "publish": "applied"}[action]}

        def finish(self, *, activate):
            assert activate is True
            steps.append("activate")
            record = versions.load(self.root)
            record.update(
                phase="starting", package=versions.package_identity(self.target), owner_instance_id="f" * 32
            )
            versions.save(self.root, record)
            (data / "runtime" / update.FENCE).unlink(missing_ok=True)
            return {"phase": "applied"}

    monkeypatch.setattr(update, "UpgradeImage", Client)
    parent = "/private/tmp" if sys.platform == "darwin" else None
    with tempfile.TemporaryDirectory(prefix="asui-", dir=parent) as temporary:
        channel = Path(temporary).resolve()
        monkeypatch.setattr(desktop, "control_directory", lambda root: channel)
        yield SimpleNamespace(
            root=root,
            config=config,
            data=data,
            old=old,
            app=app,
            source=source,
            value=value,
            progress=progress,
            steps=steps,
            clients=clients,
            answer=answer,
            engine=engine,
            channel=channel,
        )


def test_accepted_native_update_stops_old_owner_and_holds_lock_until_start_callback(setup):
    with owner(setup.root, setup.config, setup.channel) as (process, instance):

        def opened(installed):
            setup.steps.append("start")
            assert installed == setup.root / "releases" / setup.value["bundle_id"]
            assert desktop.manifest(installed) == setup.value
            assert versions.load(setup.root)["phase"] == "starting"
            assert (setup.root / ("stop-" + instance)).exists()
            process.wait(timeout=3)
            with (setup.root / "desktop.lock").open("a") as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return installed

        result = update.install_update(setup.root, setup.app, console=True, start=opened)
    assert result == update.active_payload(setup.root, desktop.manifest(setup.old))
    assert setup.steps == ["image", "bridge", "prepare", "publish", "activate", "start"]
    assert setup.progress.closed and (setup.data / "keep.txt").read_text() == "original private data"


def test_cancel_keeps_original_owner_without_constructing_an_image_transaction(setup):
    setup.answer[0] = 1
    with owner(setup.root, setup.config, setup.channel) as (process, instance):
        before = versions.load(setup.root)
        assert (
            update.install_update(setup.root, setup.app, console=True, start=lambda *_: pytest.fail("start"))
            is None
        )
        assert process.poll() is None and not (setup.root / ("stop-" + instance)).exists()
        assert versions.load(setup.root) == before
    assert not setup.clients and setup.progress.closed


@pytest.mark.parametrize("failure", ["archive", "bridge", "copy_manifest", "file_hash"])
def test_failed_package_preparation_never_stops_the_working_version(setup, monkeypatch, failure):
    if failure == "archive":
        monkeypatch.setattr(
            desktop, "import_image", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("image invalid"))
        )
    elif failure == "bridge":
        monkeypatch.setattr(update, "check_bridge", lambda *a: False)
    elif failure == "file_hash":
        (setup.source / "station").write_text("changed source bytes")
    else:
        original = desktop.shutil.copytree

        def changed(source, target, **kwargs):
            result = original(source, target, **kwargs)
            value = json.loads((target / "desktop-manifest.json").read_text())
            value["version"] = "0.3.0"
            (target / "desktop-manifest.json").write_text(json.dumps(value))
            return result

        monkeypatch.setattr(desktop.shutil, "copytree", changed)
    with owner(setup.root, setup.config, setup.channel) as (process, instance):
        if failure == "bridge":
            assert (
                update.install_update(
                    setup.root, setup.app, console=True, start=lambda *_: pytest.fail("start")
                )
                is None
            )
        else:
            with pytest.raises((ValueError, RuntimeError)):
                update.install_update(
                    setup.root, setup.app, console=True, start=lambda *_: pytest.fail("start")
                )
        assert process.poll() is None and not (setup.root / ("stop-" + instance)).exists()
    assert not setup.clients and setup.progress.closed


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform", "Linux"),
        ("architecture", "arm64"),
        ("minimum_os", "99.0"),
        ("minimum_os", "invalid"),
        ("desktop_protocol", 999),
    ],
)
def test_wrong_platform_or_protocol_is_rejected_before_import_or_stop(setup, field, value):
    payload = setup.value | {field: value}
    (setup.source / "desktop-manifest.json").write_text(json.dumps(payload))
    with owner(setup.root, setup.config, setup.channel) as (process, _):
        with pytest.raises(ValueError, match="this Mac"):
            update.install_update(setup.root, setup.app, console=True, start=lambda *_: pytest.fail("start"))
        assert process.poll() is None
    assert not setup.steps and not setup.clients


def test_version_comparison_accepts_equivalent_patch_zero(setup, monkeypatch):
    monkeypatch.setattr(platform, "mac_ver", lambda: ("13.3", (), ""))
    update.compatible(setup.value | {"minimum_os": "13.3.0"})


def test_cold_pending_update_uses_same_retained_operation_and_keeps_lock_through_start(setup, monkeypatch):
    import desktop_upgrade_image as image
    from test_desktop_upgrade_image import Daemon

    with owner(setup.root, setup.config, setup.channel) as (process, instance):
        request(setup.channel, "stop", instance_id=instance)
        process.wait(timeout=3)
    installed = desktop.install_copy(setup.root, setup.source, setup.value)
    daemon = Daemon()
    monkeypatch.setattr(image, "command", daemon)
    from uuid import uuid4

    identity = str(uuid4())
    original = image.UpgradeImage(
        setup.root, setup.config, setup.engine, fixtures.PACKAGE, setup.value, identity
    )
    original.run("prepare")
    assert update.pending(setup.root)["operation_id"] == identity

    def opened(path):
        assert path == installed
        with (setup.root / "desktop.lock").open("a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return path

    assert update.install_update(setup.root, None, console=True, start=opened) == installed
    assert setup.clients[0].identity == identity
    assert setup.steps == ["image", "bridge", "status", "publish", "activate"]


def test_active_payload_never_redirects_to_changed_code_or_changed_storage(setup):
    with owner(setup.root, setup.config, setup.channel) as (process, instance):
        request(setup.channel, "stop", instance_id=instance)
        process.wait(timeout=3)
    installed = desktop.install_copy(setup.root, setup.source, setup.value)
    record = versions.load(setup.root) | {
        "package": versions.package_identity(setup.value),
        "phase": "starting",
    }
    versions.save(setup.root, record)
    assert update.active_payload(setup.root, desktop.manifest(setup.old)) == installed
    (installed / "station").write_text("changed bytes")
    with pytest.raises(ValueError, match="changed"):
        update.active_payload(setup.root, desktop.manifest(setup.old))
    setup.config.write_text(setup.config.read_text().replace("ai-station-test", "another-project"))
    with pytest.raises(ValueError, match="storage changed"):
        update.active_payload(setup.root, desktop.manifest(setup.old))


def test_native_update_entry_does_not_bypass_the_consumer_prerequisite_gate(setup, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["desktop.py", "--console", "--install-update", str(setup.app)])
    monkeypatch.setattr(desktop.signal, "signal", lambda *a: None)
    with owner(setup.root, setup.config, setup.channel) as (process, _):
        with pytest.raises(RuntimeError, match="Linux x86-64"):
            desktop.main()
        assert process.poll() is None
    assert not setup.steps and not setup.clients


def test_reexecute_forwards_only_startup_flags_and_scrubs_other_station_settings(setup, monkeypatch):
    args = SimpleNamespace(console=False, background=True, host_port=None, install_update=setup.app)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", "/unrelated-station")
    monkeypatch.setenv("PYTHONPATH", "/unrelated-python")
    seen = {}

    def execute(program, argv, env):
        seen.update(program=program, argv=argv, env=env)
        raise OSError("neutral exec boundary")

    monkeypatch.setattr(desktop.os, "execve", execute)
    with pytest.raises(OSError):
        desktop.reexecute(setup.old, args)
    assert seen["argv"] == [
        str(setup.old / "python/bin/python3"),
        "-IB",
        str(setup.old / "scripts/desktop.py"),
        "--background",
    ]
    assert "AI_STATION_DATA_HOST_PATH" not in seen["env"] and "PYTHONPATH" not in seen["env"]
