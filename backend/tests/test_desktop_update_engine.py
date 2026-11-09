import socket
from types import SimpleNamespace
from unittest.mock import Mock

import desktop_linux_update as module
import desktop_project
import pytest
from test_desktop_versions import installation as installation


@pytest.mark.parametrize(
    "daemon,record,expected,allowed",
    [
        ("owned-daemon", {"daemon": "owned-daemon"}, None, True),
        ("foreign-daemon", {"daemon": "owned-daemon"}, None, False),
        ("owned-daemon", None, None, False),
        ("owned-daemon", None, "owned-daemon", True),
        ("foreign-daemon", None, "owned-daemon", False),
        ("owned-daemon", {"daemon": "foreign-daemon"}, "owned-daemon", False),
    ],
)
def test_native_update_admits_only_the_supervisors_recorded_daemon(
    installation, monkeypatch, daemon, record, expected, allowed
):
    root, config, _ = installation
    engine = SimpleNamespace(identity=("/usr/bin/docker", "unix:///run/docker.sock"))
    monkeypatch.setattr(module, "local_engine", lambda environment: engine)
    factory = Mock(return_value=SimpleNamespace(record=record, daemon=lambda: daemon))
    monkeypatch.setattr(desktop_project, "DesktopProject", factory)
    if allowed:
        assert module.attested_engine(root, root, expected_daemon=expected) is engine
    else:
        with pytest.raises(ValueError, match="original owned Docker connection"):
            module.attested_engine(root, root, expected_daemon=expected)
    assert factory.call_args.args[0] == config


def test_local_engine_pins_a_normal_canonical_socket_alias(tmp_path, monkeypatch):
    real = tmp_path / "run"
    real.mkdir()
    alias = tmp_path / "var-run"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(module.shutil, "which", lambda *args, **kwargs: "/usr/bin/true")
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(real / "docker.sock"))
        engine = module.local_engine({"DOCKER_HOST": "unix://" + str(alias / "docker.sock")})
    assert engine.identity[1] == "unix://" + str(real / "docker.sock")
    assert engine.environment["DOCKER_HOST"] == engine.identity[1]
    assert engine.prefix[1:] == ("--host", engine.identity[1])


def test_local_engine_refuses_a_regular_file_instead_of_a_socket(tmp_path, monkeypatch):
    path = tmp_path / "docker.sock"
    path.touch()
    monkeypatch.setattr(module.shutil, "which", lambda *args, **kwargs: "/usr/bin/true")
    with pytest.raises(ValueError, match="must be a Unix socket"):
        module.local_engine({"DOCKER_HOST": "unix://" + str(path)})
