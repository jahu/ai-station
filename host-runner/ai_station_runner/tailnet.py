"""Pure boundaries for an optional owned tailnet adapter; no lifecycle is exposed yet."""

import re
from pathlib import Path


def _absolute(path: Path) -> str:
    value = str(path)
    if not path.is_absolute() or ".." in path.parts or any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError("Tailnet paths must be trusted absolute native paths")
    return value


def daemon_argv(binary: Path, state_dir: Path, socket: Path) -> list[str]:
    return [
        _absolute(binary),
        "--tun=userspace-networking",
        "--no-logs-no-support",
        "--encrypt-state=false",
        "--hardware-attestation=false",
        "--syspolicy-file=",
        "--statedir=" + _absolute(state_dir),
        "--state=" + _absolute(state_dir / "tailscaled.state"),
        "--socket=" + _absolute(socket),
        "--port=0",
    ]


def cli_argv(binary: Path, socket: Path, operation: str, *, ui_port: int = 8765) -> list[str]:
    """The future manager supplies its configured port, never an HTTP caller target."""
    base = [_absolute(binary), "--socket=" + _absolute(socket)]
    if operation == "status":
        return [*base, "status", "--json"]
    if type(ui_port) is not int or not 1 <= ui_port <= 65535:
        raise ValueError("Invalid configured UI port")
    if operation == "serve_on":
        return [*base, "serve", "--bg", "--https=443", "--yes", f"http://127.0.0.1:{ui_port}"]
    if operation == "serve_off":
        return [*base, "serve", "--https=443", "off"]
    raise ValueError("Unsupported private-access operation")


def https_origin(dns_name: str) -> str:
    if not isinstance(dns_name, str):
        raise ValueError("Missing owned tailnet DNS name")
    host = dns_name.removesuffix(".").lower()
    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 4
        or labels[-2:] != ["ts", "net"]
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise ValueError("Choose the exact owned HTTPS tailnet hostname")
    return "https://" + host


def public_status(raw: dict) -> dict:
    """Never return keys, peer/user records or an interactive login URL."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid native tailnet status")
    state = raw.get("BackendState")
    if not isinstance(state, str) or state not in {
        "NoState",
        "NeedsLogin",
        "NeedsMachineAuth",
        "Stopped",
        "Starting",
        "Running",
    }:
        return {"state": "unknown", "node_online": False, "login_required": False}
    answer = {"state": state, "node_online": False, "login_required": state == "NeedsLogin"}
    own = raw.get("Self")
    if state == "Running" and isinstance(own, dict) and own.get("Online") is True:
        try:
            origin = https_origin(own.get("DNSName"))
        except ValueError:
            return answer
        node_id = own.get("ID")
        if isinstance(node_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", node_id):
            answer.update(node_online=True, origin=origin, node_id=node_id)
    return answer


def exact_serve_config(raw: dict, origin: str, *, ui_port: int = 8765) -> bool:
    """Unexpected configuration must be inspected, never blindly reset or adopted."""
    if not isinstance(origin, str) or not origin.startswith("https://"):
        return False
    try:
        normalized = https_origin(origin.removeprefix("https://"))
    except ValueError:
        return False
    if normalized != origin or type(ui_port) is not int or not 1 <= ui_port <= 65535:
        return False
    authority = origin.removeprefix("https://") + ":443"
    expected = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {authority: {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{ui_port}"}}}},
    }
    if not isinstance(raw, dict):
        return False
    tcp = raw.get("TCP")
    if (
        not isinstance(tcp, dict)
        or not isinstance(tcp.get("443"), dict)
        or tcp["443"].get("HTTPS") is not True
    ):
        return False
    if "AllowFunnel" in raw:
        funnel = raw["AllowFunnel"]
        if not isinstance(funnel, dict) or set(funnel) != {authority} or funnel[authority] is not False:
            return False
    return raw == expected or raw == {**expected, "AllowFunnel": {authority: False}}
