"""SSRF checks for the HTTP tool."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFBlocked(Exception):
    pass


def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SSRFBlocked("Only http and https URLs are allowed")
    host = parsed.hostname
    if not host:
        raise SSRFBlocked("URL has no host")
    if host.endswith(".local") or host == "localhost":
        raise SSRFBlocked("Local hostnames are blocked")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise SSRFBlocked("Host did not resolve") from exc
    if not infos:
        raise SSRFBlocked("Host did not resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SSRFBlocked(f"Address {ip} is not a public destination")
