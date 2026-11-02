"""Actual neutral CLI processes exercise desktop routing without a Docker daemon."""

import io
import json
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import desktop
import desktop_engine
import httpx
import launch
import macos_desktop_docker
import pytest


@pytest.fixture
def installed(tmp_path, monkeypatch):
    binary = tmp_path / "Applications/Docker.app/Contents/Resources/bin/docker"
    binary.parent.mkdir(parents=True)
    journal, imported = tmp_path / "commands.jsonl", tmp_path / "imported"
    endpoint = "unix:///Users/neutral/.docker/run/docker.sock"
    image = "sha256:" + "b" * 64
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"journal=Path({str(journal)!r}); imported=Path({str(imported)!r})\n"
        "args=sys.argv[1:]\n"
        "with journal.open('a') as stream:\n"
        " stream.write(json.dumps({'args':args,'env':dict(os.environ)})+'\\n')\n"
        "if args[:3]==['context','inspect','desktop-linux']:\n"
        f" print({endpoint!r}); sys.exit(0)\n"
        f"if args[:2]!=['--host',{endpoint!r}]:sys.exit(89)\n"
        "args=args[2:]\n"
        "if args[:2]==['image','inspect']:\n"
        " if not imported.exists():sys.exit(1)\n"
        f" print({image!r})\n"
        "elif args[:1]==['load']:imported.write_text('owned neutral fixture')\n"
        "elif args[:1]==['compose'] and 'exec' in args:\n"
        " print('http://127.0.0.1:8765/#/?setup_token='+'a'*43)\n"
    )
    binary.chmod(0o755)
    monkeypatch.setattr(desktop_engine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(macos_desktop_docker, "application_binaries", lambda: (binary,))
    monkeypatch.setattr(macos_desktop_docker.shutil, "which", lambda _: None)
    return SimpleNamespace(binary=binary, endpoint=endpoint, journal=journal, image=image)


def observations(fixture):
    return [json.loads(line) for line in fixture.journal.read_text().splitlines()]


def test_isolated_supervisor_imports_helper_from_its_own_bundle(tmp_path):
    # The development venv may have an old editable Runner. Supply only the
    # current Runner source as its installed-package stand-in; deliberately do
    # not add scripts or backend to the isolated child's module search path.
    root = Path(__file__).resolve().parents[2]
    code = (
        "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
        "source=sys.argv[2];sys.argv=[source,'--help'];runpy.run_path(source,run_name='__main__')"
    )
    result = desktop_engine.subprocess.run(
        [sys.executable, "-IB", "-c", code, str(root / "host-runner"), str(root / "scripts/launch.py")],
        cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": "/not-an-import-source"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "--desktop" in result.stdout and not result.stderr


def test_native_import_load_reinspection_use_one_selected_engine(installed, tmp_path, monkeypatch):
    # Shell routing, credentials and remote BuildKit must not reach the engine.
    for name in (
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
        "BUILDX_BUILDER",
        "BUILDKIT_HOST",
    ):
        monkeypatch.setenv(name, "PRIVATE_OTHER_STATION")
    monkeypatch.setenv("DOCKER_HOST", "ssh://other.invalid")
    engine = desktop_engine.select(desktop.launch_environment())
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    archive = bundle / "control-plane.tar"
    tag = "ai-station:desktop-" + "a" * 16
    contents = json.dumps([{"RepoTags": [tag]}]).encode()
    with tarfile.open(archive, "w") as stream:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(contents)
        stream.addfile(info, io.BytesIO(contents))
    value = {
        "image_tag": tag,
        "image_id": installed.image,
        "files": {"control-plane.tar": desktop.digest(archive)},
    }
    with (tmp_path / "desktop.log").open("w") as log:
        desktop.import_image(bundle, value, log, engine=engine)
    rows = observations(installed)
    assert [row["args"][:2] for row in rows] == [
        ["context", "inspect"],
        ["--host", installed.endpoint],
        ["--host", installed.endpoint],
        ["--host", installed.endpoint],
    ]
    assert rows[2]["args"][2:4] == ["load", "--input"]
    for row in rows[1:]:
        env = row["env"]
        assert env["DOCKER_HOST"] == installed.endpoint
        assert not any(value == "PRIVATE_OTHER_STATION" for value in env.values())
        assert env["PATH"] == str(installed.binary.parent) + os.pathsep + os.defpath
    # No rediscovery between image inspection/load/identity verification.
    assert len(rows) == 4


@pytest.mark.parametrize("fail_up", [False, True])
def test_supervisor_bootstrap_and_shutdown_keep_exact_engine(installed, tmp_path, monkeypatch, fail_up):
    env = {
        "AI_STATION_DATA_HOST_PATH": str(tmp_path),
        "COMPOSE_PROJECT_NAME": "ai-station-neutral-test",
        "DOCKER_CONTEXT": "remote-fixture",
        "DOCKER_HOST": "tcp://remote.invalid:2375",
    }
    monkeypatch.setattr(launch, "configuration", lambda: env)
    monkeypatch.setattr(launch.os, "chdir", lambda _: None)
    monkeypatch.setattr(launch.signal, "signal", lambda *args: None)
    monkeypatch.setattr(launch, "runner_health", lambda _: True)
    monkeypatch.setattr(
        launch.sys,
        "argv",
        [
            "launch.py",
            "--no-build",
            "--desktop",
            "--docker-desktop-cli",
            str(installed.binary),
            "--docker-desktop-endpoint",
            installed.endpoint,
        ],
    )
    monkeypatch.setattr(launch.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    original_run = launch.subprocess.run

    def execute(argv, **kwargs):
        result = original_run(argv, **kwargs)
        if fail_up and "up" in argv:
            raise launch.subprocess.CalledProcessError(7, argv)
        return result

    monkeypatch.setattr(launch.subprocess, "run", execute)
    instance = "d" * 32
    monkeypatch.setenv("AI_STATION_DESKTOP_INSTANCE_ID", instance)
    env["AI_STATION_DESKTOP_INSTANCE_ID"] = instance
    original_client = httpx.Client

    def reply(request):
        payload = (
            {"setup_required": True}
            if request.url.path == "/api/auth"
            else {
                "status": "ok",
                "desktop_instance_id": instance,
            }
        )
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        launch.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(reply))
    )
    if fail_up:
        with pytest.raises(launch.subprocess.CalledProcessError):
            launch.main()
    else:
        launch.main()
    rows = observations(installed)
    assert rows[0]["args"][:3] == ["context", "inspect", "desktop-linux"]
    commands = [row["args"][2:] for row in rows[1:]]
    assert all(command[:1] == ["compose"] for command in commands)
    assert commands[0][-3:] == ["ps", "--all", "--quiet"]
    assert commands[1][-6:] == ["up", "--no-build", "--detach", "--wait", "--wait-timeout", "120"]
    assert commands[-1][-3:] == ["down", "--timeout", "10"]
    if not fail_up:
        assert commands[2][-8:] == [
            "exec",
            "-T",
            "ai-station",
            "python",
            "-m",
            "app.bootstrap_setup",
            "--url",
            "http://127.0.0.1:8765",
        ]
    assert not any("--volumes" in command or "--rmi" in command for command in commands)
    assert all(row["args"][:2] == ["--host", installed.endpoint] for row in rows[1:])
    assert all(row["env"].get("DOCKER_CONTEXT") is None for row in rows[1:])
    assert all(row["env"]["COMPOSE_PROJECT_NAME"] == env["COMPOSE_PROJECT_NAME"] for row in rows[1:])


@pytest.mark.parametrize("changed", ["binary", "endpoint"])
def test_replaced_desktop_connection_refuses_before_any_engine_operation(installed, changed):
    expected = (str(installed.binary), installed.endpoint)
    expected = (
        (expected[0] + "-other", expected[1]) if changed == "binary" else (expected[0], "unix:///other.sock")
    )
    with pytest.raises(RuntimeError, match="changed during startup"):
        desktop_engine.select({}, expected=expected)
    assert len(observations(installed)) == 1  # Read-only context lookup only.


def test_linux_engine_keeps_existing_routing_without_macos_discovery(monkeypatch):
    monkeypatch.setattr(desktop_engine.platform, "system", lambda: "Linux")
    monkeypatch.setattr(macos_desktop_docker, "connection", lambda _: pytest.fail("Mac discovery on Linux"))
    env = {"DOCKER_CONTEXT": "existing-local", "PATH": "/original/path"}
    selected = desktop_engine.select(env)
    assert selected.command("compose", "version") == ["docker", "compose", "version"]
    assert selected.environment == env and selected.environment is not env
    assert selected.identity is None
    with pytest.raises(RuntimeError, match="native Mac"):
        desktop_engine.select(env, expected=("/fixture", "unix:///fixture"))


def test_consumer_gate_is_not_removed_by_docker_routing(installed):
    with pytest.raises(RuntimeError, match="Linux x86-64"):
        desktop.prerequisites()
    assert not installed.journal.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--docker-desktop-cli", "/not-executed"],
        ["--desktop", "--docker-desktop-endpoint", "unix:///not-executed.sock"],
        ["--docker-desktop-cli", "/not-executed", "--docker-desktop-endpoint", "unix:///fixture.sock"],
    ],
)
def test_incomplete_or_non_desktop_handoff_never_reaches_configuration(monkeypatch, arguments):
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", *arguments])
    monkeypatch.setattr(launch, "configuration", lambda: pytest.fail("Unexpected configuration write"))
    with pytest.raises(RuntimeError, match="handoff requires both coordinates"):
        launch.main()


def test_parent_handoff_uses_sanitized_engine_environment(installed, tmp_path, monkeypatch):
    engine = desktop_engine.select({"DOCKER_CONTEXT": "PRIVATE_OTHER_STATION"})
    monkeypatch.setenv("DOCKER_CONTEXT", "PRIVATE_OTHER_STATION")
    proc = Mock()
    proc.stdout = io.StringIO(
        desktop.READY
        + json.dumps(
            {
                "url": "http://127.0.0.1:8766",
                "instance_id": "d" * 32,
            }
        )
        + "\n"
    )
    proc.poll.return_value = None
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    monkeypatch.setattr(desktop.webbrowser, "open", Mock())
    monkeypatch.setattr(desktop, "running_window", lambda *args, **kwargs: "stop")
    desktop.supervise(
        tmp_path,
        tmp_path / "desktop.env",
        {"image_tag": "neutral"},
        io.StringIO(),
        engine=engine,
        instance_id="d" * 32,
    )
    argv = spawn.call_args.args[0]
    assert argv[-4:] == [
        "--docker-desktop-cli",
        str(installed.binary),
        "--docker-desktop-endpoint",
        installed.endpoint,
    ]
    env = spawn.call_args.kwargs["env"]
    assert env.get("DOCKER_CONTEXT") is None and env["DOCKER_HOST"] == installed.endpoint
    assert env["AI_STATION_APP_IMAGE"] == "neutral"
    assert env["AI_STATION_DESKTOP_INSTANCE_ID"] == "d" * 32
    assert env["PATH"].startswith(str(installed.binary.parent) + os.pathsep)
    proc.terminate.assert_called_once()


def test_failed_context_with_plausible_stdout_is_not_accepted(installed):
    with pytest.raises(RuntimeError, match="complete its local setup"):
        macos_desktop_docker.connection(lambda *args, **kwargs: (1, installed.endpoint))


@pytest.mark.parametrize(
    "failure", [OSError("PRIVATE_FIXTURE"), desktop_engine.subprocess.TimeoutExpired("fixture", 15)]
)
def test_context_process_failure_has_actionable_message_without_private_output(monkeypatch, failure):
    monkeypatch.setattr(desktop_engine.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(RuntimeError, match="Open Docker Desktop") as error:
        desktop_engine.context_command(["neutral-not-executed"], env={})
    assert "PRIVATE_FIXTURE" not in str(error.value)
