from uuid import uuid4

import pytest
from ai_station_runner.desktop_update_channel import request
from desktop_control import DesktopControl


@pytest.mark.parametrize("phase", ["failed", "inspection_required", "canceled"])
def test_operation_failure_is_status_not_a_transport_rejection(tmp_path, phase):
    tmp_path.chmod(0o700)
    identity = str(uuid4())
    result = {"run_id": identity, "phase": phase, "error": "The native update was not applied"}

    class Updates:
        def handle(self, value):
            return result

    with DesktopControl(tmp_path, updates=Updates()) as control:
        assert request(control.path, {"action": "updates.inspect", "run_id": identity}) == result


def test_error_only_protocol_envelope_still_rejects_an_invalid_operation(tmp_path):
    tmp_path.chmod(0o700)

    class Updates:
        def handle(self, value):
            raise ValueError("The native operation identity changed")

    with DesktopControl(tmp_path, updates=Updates()) as control:
        with pytest.raises(ValueError, match="identity changed"):
            request(control.path, {"action": "updates.inspect", "run_id": str(uuid4())})
