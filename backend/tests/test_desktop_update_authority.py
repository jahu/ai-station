from uuid import uuid4

import desktop_linux_update as linux
import desktop_update_authority as native
import pytest
from ai_station_runner.desktop_update_channel import command, request
from app.config import get_settings
from app.db import control_session_factory
from app.models import Run, User
from app.station_update_gate import take
from desktop_control import DesktopControl
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_desktop_linux_update import OWNER, PACKAGE
from test_station_update_gate import updating


def installation(tmp_path):
    root = tmp_path / "native"
    root.mkdir(mode=0o700)
    data = get_settings().data_dir.resolve()
    data.chmod(0o700)
    (data / "db").chmod(0o700)
    config = root / "desktop.env"
    config.write_text(
        f'AI_STATION_DATA_HOST_PATH="{data}"\n'
        f'AI_STATION_RUNNER_SOCKET="{root}/runner/runner.sock"\n'
        'COMPOSE_PROJECT_NAME="ai-station-qa"\nAI_STATION_ACCESS_PROFILE="accounts"\n'
    )
    config.chmod(0o600)
    linux.ready(root, PACKAGE | {"version": "0.4.0", "release_version": "0.4.0"}, config, OWNER)
    return root


def test_native_rechecks_live_administrator_and_exact_idle_gate(accounts, tmp_path):
    identity, claim = updating(accounts)
    root = installation(tmp_path)
    proof = native.authority(root, identity)
    assert proof["request"]["release_id"] == 123 and proof["canceled"] is False
    with pytest.raises(ValueError, match="idle dispatch gate"):
        native.authority(root, identity, idle=True)
    take(identity, claim)
    assert native.authority(root, identity, expected=proof["request"], idle=True) == proof
    with control_session_factory()() as session:
        session.get(User, session.get(Run, identity).owner_id).is_admin = False
        session.commit()
    with pytest.raises(ValueError, match="administrator authority"):
        native.authority(root, identity, idle=True)


@pytest.mark.parametrize("mutation", ["request", "role", "cancel", "claim", "version"])
def test_native_rejects_changed_request_role_or_claim_before_stop(accounts, tmp_path, mutation):
    identity, claim = updating(accounts)
    root = installation(tmp_path)
    proof = native.authority(root, identity)
    take(identity, claim)
    with control_session_factory()() as session:
        row = session.get(Run, identity)
        if mutation == "request":
            row.parameters = {**row.parameters, "fingerprint": "b" * 64}
        elif mutation == "role":
            session.get(User, row.owner_id).enabled = False
        elif mutation == "cancel":
            row.status = "cancel_requested"
        elif mutation == "claim":
            row.worker_id = "replacement-worker"
        else:
            row.parameters = {**row.parameters, "current_version": "0.1.0"}
        session.commit()
    with pytest.raises(ValueError):
        native.authority(root, identity, expected=proof["request"], idle=True)


def test_native_message_does_not_accept_urls_paths_commands_or_noncanonical_ids():
    good = {
        "action": "updates.prepare",
        "run_id": str(uuid4()),
        "request": {
            "release_id": 123,
            "fingerprint": "a" * 64,
            "current_version": "0.4.0",
            "platform": "linux-amd64",
        },
    }
    assert command(good) == good
    for value in (
        good | {"url": "https://other.example"},
        good | {"action": "shell"},
        good | {"run_id": "../../other"},
        good | {"request": {**good["request"], "command": "install"}},
        good | {"request": {**good["request"], "platform": []}},
    ):
        with pytest.raises(ValueError):
            command(value)


def test_actual_private_socket_preserves_existing_controls_and_only_dispatches_typed_updates(tmp_path):
    tmp_path.chmod(0o700)
    seen = []

    class Updates:
        def handle(self, value):
            seen.append(value)
            return {"installed": True, "version": "0.5.0"}

    with DesktopControl(tmp_path, updates=Updates()) as control:
        result = request(control.path, {"action": "updates.capabilities"})
        assert result["installed"] and result["version"] == "0.5.0"
        assert seen == [{"action": "updates.capabilities"}]
    assert not control.path.exists()
