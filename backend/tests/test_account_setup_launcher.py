"""Launcher obtains first-setup authority only from the owned console."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from launch import local_entry_url


@pytest.mark.parametrize("port", [8765, 5173])
def test_pending_setup_uses_the_api_port_and_fixed_owned_container_console(port):
    ui = f"http://127.0.0.1:{port}"
    proof_url = ui + "/#/?setup_token=" + "a" * 43
    calls = []

    def auth(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"setup_required": True})

    run = Mock(return_value=SimpleNamespace(stdout=proof_url + "\n"))
    with httpx.Client(transport=httpx.MockTransport(auth)) as client:
        assert local_entry_url(client, run, ui, "http://127.0.0.1:8765") == proof_url
    assert calls == ["http://127.0.0.1:8765/api/auth"]
    run.assert_called_once_with(
        "exec",
        "-T",
        "ai-station",
        "python",
        "-m",
        "app.bootstrap_setup",
        "--url",
        ui,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "status,body,content_type",
    [
        (404, {}, "application/json"),
        (200, {}, "text/html"),
        (200, {"setup_required": False}, "application/json"),
        (200, {"setup_required": "true"}, "application/json"),
        (200, [], "application/json"),
    ],
)
def test_legacy_or_configured_profiles_never_request_a_setup_proof(status, body, content_type):
    run = Mock()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, json=body, headers={"Content-Type": content_type})
        )
    ) as client:
        url = "http://127.0.0.1:8765"
        assert local_entry_url(client, run, url, url) == url
    run.assert_not_called()
