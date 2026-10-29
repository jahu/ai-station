"""Startup recovery never takes ownership of another stack or a live worker."""

import fcntl
import json
import os
import socket
from copy import deepcopy
from pathlib import Path

import pytest
import recover_control_plane as recovery


@pytest.fixture
def stack(tmp_path, monkeypatch):
    for key in [
        "COMPOSE_PROJECT_NAME",
        "AI_STATION_LAN_HOST",
        "AI_STATION_PORT",
        "AI_STATION_DATA_HOST_PATH",
        "AI_STATION_RUNNER_SOCKET",
    ]:
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    for name in ["compose.yaml", "compose.lan.yaml", "host-runner/ai_station_runner/source_identity.py"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SOURCE_FINGERPRINT = 'fixture'" if name.endswith(".py") else "services: {}")
    data = tmp_path / "data"
    (data / "runtime/runner").mkdir(parents=True)
    (data / "runtime").chmod(0o775)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env_file = root / ".env"
    env_file.write_text(
        f"COMPOSE_PROJECT_NAME=ai-station-recovery-test\nAI_STATION_DATA_HOST_PATH={data}\nAI_STATION_PORT={port}\n"
    )
    cfg = recovery.configuration(root)
    items = []
    for index, role in enumerate(["ai-station", "worker", "scheduler"]):
        bindings = (
            {"8765/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]} if role == "ai-station" else {}
        )
        items.append(
            {
                "Id": str(index + 1) * 64,
                "Image": "sha256:" + "a" * 64,
                "Config": {
                    "User": f"{os.getuid()}:{os.getgid()}",
                    "Labels": {
                        "com.docker.compose.project": cfg.project,
                        "com.docker.compose.service": role,
                        "com.docker.compose.project.working_dir": str(root),
                        "com.docker.compose.project.config_files": ",".join(map(str, cfg.files)),
                    },
                },
                "HostConfig": {
                    "Privileged": False,
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PortBindings": bindings,
                },
                "Mounts": [
                    {"Type": "bind", "Destination": destination, "Source": str(source), "RW": writable}
                    for destination, source, writable in [
                        ("/data", cfg.data, True),
                        ("/runner", cfg.socket.parent, False),
                    ]
                ],
                "NetworkSettings": {"Ports": deepcopy(bindings)},
                "State": {"Running": True, "Status": "running", "Error": ""},
            }
        )
    state = {"items": items, "commands": [], "health": True}
    service = recovery.Recovery(cfg, wait_seconds=0)

    def command(argv, timeout=20):
        state["commands"].append(argv)
        if argv[:3] == ["docker", "context", "inspect"]:
            return state.get("endpoint", "unix:///var/run/docker.sock")
        if argv[:2] == ["docker", "inspect"]:
            return json.dumps(
                [item for identifier in argv[2:] for item in state["items"] if item["Id"] == identifier]
            )
        if "ps" in argv:
            return "\n".join(item["Id"] for item in state["items"])
        if "up" in argv:
            pin = Path(argv[argv.index("up") - 1])
            assert json.loads(pin.read_text()) == {"services": {"ai-station": {"image": items[0]["Image"]}}}
            items[0]["State"].update(Running=True, Status="running", Error="")
            items[0]["NetworkSettings"]["Ports"] = deepcopy(items[0]["HostConfig"]["PortBindings"])
            items[0]["Config"]["Labels"]["com.docker.compose.project.config_files"] = ",".join(
                map(str, [*cfg.files, pin])
            )
            state["health"] = True
            return ""
        if argv[:2] == ["docker", "start"]:
            next(item for item in items if item["Id"] == argv[2])["State"].update(
                Running=True, Status="running"
            )
            return argv[2]
        raise AssertionError(argv)

    monkeypatch.setattr(service, "command", command)
    monkeypatch.setattr(service, "health", lambda: state["health"])
    monkeypatch.setattr(service, "runner_ready", lambda: True)
    monkeypatch.setattr(service, "addresses_ready", lambda: True)
    return service, state


def mutations(state):
    return [cmd for cmd in state["commands"] if "up" in cmd or cmd[:2] == ["docker", "start"]]


def fail_binding(state, *, running=False):
    state["items"][0]["NetworkSettings"]["Ports"] = {}
    state["items"][0]["State"].update(
        Running=running,
        Status="running" if running else "exited",
        Error="failed to bind host port: cannot assign requested address",
    )
    state["health"] = False


def test_healthy_existing_stack_is_read_only(stack):
    service, state = stack
    assert service.run() == {"status": "healthy", "changed": False}
    assert not mutations(state)


@pytest.mark.parametrize("context", [False, True])
def test_remote_docker_hosts_and_context_overrides_are_not_used(stack, context):
    service, state = stack
    service.config.env["DOCKER_HOST"] = "unix:///var/run/docker.sock" if context else "ssh://another-host"
    service.config.env.pop("DOCKER_CONTEXT", None)
    if context:
        service.config.env["DOCKER_CONTEXT"] = "remote"
        state["endpoint"] = "ssh://another-host"
    with pytest.raises(ValueError, match="local Docker"):
        service.run()
    assert not mutations(state)


@pytest.mark.parametrize("running", [False, True])
def test_failed_or_empty_publish_mapping_recovers_only_api_and_pins_its_image(stack, running):
    service, state = stack
    fail_binding(state, running=running)
    workers = deepcopy(state["items"][1:])
    result = service.run()
    assert result["status"] == "recovered" and result["started_created_services"] == []
    commands = mutations(state)
    assert len(commands) == 1 and commands[0][-1] == "ai-station"
    assert all(flag in commands[0] for flag in ["--no-deps", "--no-build", "--pull", "never"])
    assert state["items"][1:] == workers
    pins = list((service.config.data / "runtime/recovery").glob("recovery-image-*.json"))
    assert len(pins) == 1 and pins[0].stat().st_mode & 0o777 == 0o600
    # The retained pin is part of the Docker provenance on the next boot.
    assert service.run()["status"] == "healthy"
    assert len(mutations(state)) == 1


def test_recovery_starts_only_never_started_created_roles(stack):
    service, state = stack
    fail_binding(state)
    state["items"][1]["State"].update(Running=False, Status="created")
    state["items"][2]["State"].update(Running=False, Status="exited", Error="")
    assert service.run()["started_created_services"] == ["worker"]
    assert mutations(state)[1] == ["docker", "start", state["items"][1]["Id"]]


def test_lost_recreate_reply_resumes_only_created_roles_without_repeating_api_repair(stack, monkeypatch):
    service, state = stack
    fail_binding(state)
    for item in state["items"][1:]:
        item["State"].update(Running=False, Status="created")
    original = service.command

    def lost_reply(argv, timeout=20):
        result = original(argv, timeout)
        if "up" in argv:
            raise recovery.subprocess.TimeoutExpired(argv, timeout)
        return result

    monkeypatch.setattr(service, "command", lost_reply)
    with pytest.raises(recovery.subprocess.TimeoutExpired):
        service.run()
    monkeypatch.setattr(service, "command", original)
    assert service.run()["started_created_services"] == ["worker", "scheduler"]
    assert service.run() == {"status": "healthy", "changed": False}
    assert len([cmd for cmd in mutations(state) if "up" in cmd]) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "project",
        "checkout",
        "user",
        "privileged",
        "writable-root",
        "caps",
        "privilege-escalation",
        "data-root",
        "writable-socket",
        "extra-mount",
        "public-port",
        "unknown-service",
        "image",
    ],
)
def test_mismatched_or_unsafe_existing_containers_are_never_changed(stack, fault):
    service, state = stack
    fail_binding(state)
    item = state["items"][0]
    if fault == "project":
        item["Config"]["Labels"]["com.docker.compose.project"] = "unrelated"
    elif fault == "checkout":
        item["Config"]["Labels"]["com.docker.compose.project.working_dir"] = "/unrelated"
    elif fault == "user":
        item["Config"]["User"] = str(os.getuid() + 1)
    elif fault == "privileged":
        item["HostConfig"]["Privileged"] = True
    elif fault == "writable-root":
        item["HostConfig"]["ReadonlyRootfs"] = False
    elif fault == "caps":
        item["HostConfig"]["CapDrop"] = []
    elif fault == "privilege-escalation":
        item["HostConfig"]["SecurityOpt"] = []
    elif fault == "data-root":
        item["Mounts"][0]["Source"] = "/unrelated"
    elif fault == "writable-socket":
        item["Mounts"][1]["RW"] = True
    elif fault == "extra-mount":
        item["Mounts"].append({"Type": "bind", "Destination": "/host", "Source": "/", "RW": True})
    elif fault == "public-port":
        item["HostConfig"]["PortBindings"]["8765/tcp"][0]["HostIp"] = "0.0.0.0"
    elif fault == "unknown-service":
        item["Config"]["Labels"]["com.docker.compose.service"] = "unrelated"
    else:
        item["Image"] = "some-new-tag"
    with pytest.raises(ValueError):
        service.run()
    assert not mutations(state)


@pytest.mark.parametrize("role", ["addresses_ready", "runner_ready"])
def test_missing_lan_or_matching_runner_waits_without_docker_mutations(stack, monkeypatch, role):
    service, state = stack
    fail_binding(state)
    monkeypatch.setattr(service, role, lambda: False)
    with pytest.raises(ValueError):
        service.run()
    assert not mutations(state)


def test_busy_port_listener_is_not_touched(stack):
    service, state = stack
    fail_binding(state)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", service.config.port))
        listener.listen()
        with pytest.raises(ValueError, match="occupied"):
            service.run()
    assert not mutations(state)


def test_stopped_missing_or_supervised_deployments_are_not_taken_over(stack):
    service, state = stack
    state["items"][0]["State"].update(Running=False, Status="exited")
    state["items"][0]["NetworkSettings"]["Ports"] = {}
    assert service.run()["changed"] is False
    state["items"].clear()
    assert service.run()["status"] == "absent"
    with (service.config.data / "runtime/launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert service.run()["status"] == "already_supervised"
    assert not mutations(state)


def test_runtime_or_lock_symlinks_do_not_redirect_recovery(stack, tmp_path):
    service, state = stack
    target = tmp_path / "unrelated"
    target.write_text("keep")
    (service.config.data / "runtime/launcher.lock").symlink_to(target)
    with pytest.raises(OSError):
        service.run()
    assert target.read_text() == "keep" and not mutations(state)


def test_changed_retained_image_pin_cannot_introduce_other_services(stack):
    service, state = stack
    fail_binding(state)
    service.run()
    pin = next((service.config.data / "runtime/recovery").glob("recovery-image-*.json"))
    pin.write_text(json.dumps({"services": {"worker": {"image": "unrelated"}}}))
    with pytest.raises(ValueError):
        service.run()
    assert len(mutations(state)) == 1


@pytest.mark.parametrize("address", ["0.0.0.0", "8.8.8.8", "127.0.0.1", "::1"])
def test_configuration_never_broadens_publish_to_public_or_wildcard(stack, monkeypatch, address):
    service, state = stack
    monkeypatch.setenv("AI_STATION_LAN_HOST", address)
    with pytest.raises(ValueError):
        recovery.configuration(service.config.root)
    assert not mutations(state)


def test_owned_user_service_installation_quotes_paths_and_preserves_unrelated_units(
    stack, tmp_path, monkeypatch
):
    service, _ = stack
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    commands = []
    monkeypatch.setattr(recovery.subprocess, "run", lambda argv, **kwargs: commands.append(argv))
    assert recovery.install_service(service.config)["status"] == "installed"
    unit = tmp_path / "config/systemd/user/ai-station-recovery.service"
    assert str(service.config.root) in unit.read_text()
    assert commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", unit.name],
    ]
    assert recovery.systemd_argument('a $MODEL% "path') == '"a $$MODEL%% \\"path"'
    unit.write_text("Unrelated service")
    with pytest.raises(ValueError):
        recovery.install_service(service.config)
    assert unit.read_text() == "Unrelated service"


def test_recovery_waits_for_real_address_readiness_before_mutating_docker(stack, monkeypatch):
    service, state = stack
    fail_binding(state)
    attempts = []

    def address_ready():
        attempts.append(True)
        return len(attempts) == 3

    service.wait_seconds = 1
    monkeypatch.setattr(service, "addresses_ready", address_ready)
    monkeypatch.setattr(recovery.time, "sleep", lambda _: None)
    assert service.run()["status"] == "recovered"
    assert len(attempts) == 3 and len(mutations(state)) == 1


def test_absent_interface_is_an_observation_not_a_network_change(stack, monkeypatch):
    service, _ = stack

    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            raise OSError(recovery.errno.EADDRNOTAVAIL, "not ready")

    monkeypatch.setattr(recovery.socket, "socket", lambda *args: Probe())
    assert recovery.Recovery.addresses_ready(service) is False


@pytest.mark.parametrize("fault", ["world-writable", "runtime-symlink", "incomplete", "scaled", "unhealthy"])
def test_ambiguous_or_insecure_startup_state_is_left_for_inspection(stack, tmp_path, fault):
    service, state = stack
    if fault == "world-writable":
        (service.config.data / "runtime").chmod(0o777)
    elif fault == "runtime-symlink":
        import shutil

        shutil.rmtree(service.config.data / "runtime")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (service.config.data / "runtime").symlink_to(elsewhere, target_is_directory=True)
    elif fault == "incomplete":
        state["items"].pop()
    elif fault == "scaled":
        state["items"].append(deepcopy(state["items"][0]))
    else:
        state["health"] = False
    with pytest.raises(ValueError):
        service.run()
    assert not mutations(state)
