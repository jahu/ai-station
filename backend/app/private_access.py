"""Explicit private UI origins; this never changes the native Runner transport."""

from ipaddress import IPv4Address, ip_address, ip_network
from urllib.parse import urlsplit

from app.config import get_settings

PRIVATE_NETWORKS = tuple(
    ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
    )
)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def private_ipv4(value: str) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return isinstance(address, IPv4Address) and any(address in net for net in PRIVATE_NETWORKS)


def access_origins() -> set[str]:
    settings = get_settings()
    origins = set()
    if settings.lan_host:
        if not private_ipv4(settings.lan_host):
            raise ValueError("AI_STATION_LAN_HOST must be a specific private IPv4 address")
        origins.add(f"http://{settings.lan_host}:{settings.port}")
    for value in settings.access_origins.split(","):
        value = value.strip()
        if not value:
            continue
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        tailnet = host.endswith(".ts.net") and parsed.scheme == "https"
        if (
            parsed.scheme not in {"http", "https"}
            or not (private_ipv4(host) or tailnet)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
            or value != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError("Access origins must be exact private IP origins or HTTPS *.ts.net origins")
        origins.add(value)
    return origins


def private_access_enabled() -> bool:
    return bool(access_origins())


def valid_host(authority: str) -> bool:
    try:
        parsed = urlsplit("http://" + authority)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return False
        if parsed.hostname in LOCAL_HOSTS:
            return True
        return any(urlsplit(origin).netloc == authority for origin in access_origins())
    except ValueError:
        return False


def valid_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        # Vite and local API clients retain the existing loopback development policy.
        local = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in LOCAL_HOSTS
            and not parsed.username
            and not parsed.password
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
        return local or origin in access_origins()
    except ValueError:
        return False


def secure_cookie(authority: str) -> bool:
    return any(
        urlsplit(origin).netloc == authority and origin.startswith("https://") for origin in access_origins()
    )
