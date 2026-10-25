"""Pure tailnet boundaries; these tests do not enroll or expose a service."""

from copy import deepcopy
from pathlib import Path

import pytest
from ai_station_runner.tailnet import cli_argv, daemon_argv, exact_serve_config, https_origin, public_status


def test_fixed_userspace_daemon_never_selects_a_system_socket_or_proxy():
    args = daemon_argv(
        Path("/owned/bin/tailscaled"), Path("/private/ai-station"), Path("/private/ai-station/daemon.sock")
    )
    assert args == [
        "/owned/bin/tailscaled",
        "--tun=userspace-networking",
        "--no-logs-no-support",
        "--encrypt-state=false",
        "--hardware-attestation=false",
        "--syspolicy-file=",
        "--statedir=/private/ai-station",
        "--state=/private/ai-station/tailscaled.state",
        "--socket=/private/ai-station/daemon.sock",
        "--port=0",
    ]
    assert not any("socks5" in a or "outbound-http" in a for a in args)


@pytest.mark.parametrize(
    "path", ["relative", "/private/../outside", "/private/evil\nname", "/private/evil\x00name"]
)
def test_builders_reject_untrusted_path_shapes(path):
    with pytest.raises(ValueError):
        daemon_argv(Path("/bin/tailscaled"), Path(path), Path("/private/daemon.sock"))


@pytest.mark.parametrize("port", [True, 0, 65536, "8765", 8765.0])
def test_no_caller_target_or_ambiguous_port_is_accepted(port):
    with pytest.raises(ValueError):
        cli_argv(Path("/bin/tailscale"), Path("/private/daemon.sock"), "serve_on", ui_port=port)


def test_cli_operations_remain_fixed_and_loopback_only():
    base = ["/bin/tailscale", "--socket=/private/daemon.sock"]
    assert cli_argv(Path(base[0]), Path("/private/daemon.sock"), "status") == [*base, "status", "--json"]
    assert cli_argv(Path(base[0]), Path("/private/daemon.sock"), "serve_on", ui_port=9000) == [
        *base,
        "serve",
        "--bg",
        "--https=443",
        "--yes",
        "http://127.0.0.1:9000",
    ]
    assert cli_argv(Path(base[0]), Path("/private/daemon.sock"), "serve_off") == [
        *base,
        "serve",
        "--https=443",
        "off",
    ]
    for operation in ["funnel", "reset", "up --advertise-exit-node", "serve /etc", "shell"]:
        with pytest.raises(ValueError):
            cli_argv(Path(base[0]), Path("/private/daemon.sock"), operation)


@pytest.mark.parametrize(
    "value",
    [
        "https://node.tail.ts.net",
        "node.tail.ts.net:443",
        "127.0.0.1",
        "node.ts.net",
        "node.tail.ts.net.evil",
        "user@node.tail.ts.net",
        "-node.tail.ts.net",
        "node.tail.ts.net/path",
        "node.tail.ts.net\n",
    ],
)
def test_origin_requires_an_exact_tailnet_hostname(value):
    with pytest.raises(ValueError):
        https_origin(value)


def test_status_projects_only_own_nonsecret_node_metadata():
    data = {
        "BackendState": "Running",
        "Self": {
            "ID": "node123",
            "Online": True,
            "DNSName": "AI-Station.tail123.ts.net.",
            "PrivateKey": "secret",
        },
        "Peer": {"other": {"HostName": "private"}},
        "User": {"secret": "profile"},
        "AuthURL": "https://login.tailscale.com/a/private-login",
    }
    assert public_status(data) == {
        "state": "Running",
        "node_online": True,
        "login_required": False,
        "origin": "https://ai-station.tail123.ts.net",
        "node_id": "node123",
    }
    assert public_status({"BackendState": "NeedsLogin", "AuthURL": data["AuthURL"]}) == {
        "state": "NeedsLogin",
        "node_online": False,
        "login_required": True,
    }
    assert public_status({"BackendState": "FutureState", "AuthURL": data["AuthURL"]}) == {
        "state": "unknown",
        "node_online": False,
        "login_required": False,
    }
    data["Self"]["Online"] = 1
    assert public_status(data)["node_online"] is False


def serve():
    return {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {"ai-station.tail123.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}},
    }


@pytest.mark.parametrize("value", [None, {}, [], 17, True])
def test_malformed_backend_state_is_unknown_without_credentials(value):
    assert public_status({"BackendState": value, "AuthURL": "secret"}) == {
        "state": "unknown",
        "node_online": False,
        "login_required": False,
    }


def test_owned_serve_shape_does_not_claim_application_or_tls_readiness():
    data = serve()
    assert exact_serve_config(data, "https://ai-station.tail123.ts.net")
    assert exact_serve_config(
        {**data, "AllowFunnel": {"ai-station.tail123.ts.net:443": False}}, "https://ai-station.tail123.ts.net"
    )


@pytest.mark.parametrize(
    "change", ["funnel", "numeric_funnel", "numeric_https", "target", "handler", "port", "unknown"]
)
def test_unexpected_configuration_cannot_be_silently_adopted(change):
    data = deepcopy(serve())
    if change in {"funnel", "numeric_funnel"}:
        data["AllowFunnel"] = {"ai-station.tail123.ts.net:443": True if change == "funnel" else 0}
    elif change == "numeric_https":
        data["TCP"]["443"]["HTTPS"] = 1
    elif change == "target":
        data["Web"]["ai-station.tail123.ts.net:443"]["Handlers"]["/"]["Proxy"] = "http://192.168.1.1/"
    elif change == "handler":
        data["Web"]["ai-station.tail123.ts.net:443"]["Handlers"]["/other"] = {"Text": "unexpected"}
    elif change == "port":
        data["TCP"]["80"] = {"HTTP": True}
    else:
        data["Unexpected"] = True
    assert not exact_serve_config(data, "https://ai-station.tail123.ts.net")
