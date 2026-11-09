from types import SimpleNamespace
from unittest.mock import Mock

import desktop_linux_update as module
import desktop_project
import pytest
from test_desktop_versions import installation as installation


@pytest.mark.parametrize(
    "daemon,record,allowed",
    [
        ("owned-daemon", {"daemon": "owned-daemon"}, True),
        ("foreign-daemon", {"daemon": "owned-daemon"}, False),
        ("owned-daemon", None, False),
    ],
)
def test_native_update_admits_only_the_supervisors_recorded_daemon(
    installation, monkeypatch, daemon, record, allowed
):
    root, config, _ = installation
    engine = SimpleNamespace(identity=("/usr/bin/docker", "unix:///run/docker.sock"))
    monkeypatch.setattr(module, "local_engine", lambda environment: engine)
    factory = Mock(return_value=SimpleNamespace(record=record, daemon=lambda: daemon))
    monkeypatch.setattr(desktop_project, "DesktopProject", factory)
    if allowed:
        assert module.attested_engine(root, root) is engine
    else:
        with pytest.raises(ValueError, match="original owned Docker connection"):
            module.attested_engine(root, root)
    assert factory.call_args.args[0] == config
