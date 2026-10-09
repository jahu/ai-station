"""GET of reviewed public URLs; never model-selected or private SSRF."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import tempfile
import time
from contextlib import suppress
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.providers import ProviderError

MAX_URL = 2000
MAX_BODY = 256 * 1024
MAX_TEXT = 8_000
MAX_REDIRECTS = 3
MAX_LINKS = 15
MAX_PAGES = 3
TIMEOUT = 20
REDIRECTS = {301, 302, 303, 307, 308}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid", ".onion")
BINARY_PREFIXES = ("image/", "audio/", "video/", "font/")
BINARY_TYPES = {
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/wasm",
}
PROMPT_URL = re.compile(r"https?://[^\s)\]>'\"<>]+", re.IGNORECASE)


def public_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_URL or re.search(r"[\s\\\x00-\x1f]", value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
            or not host
        ):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (
                "." not in host
                or host.endswith(BLOCKED_HOST_SUFFIXES)
                or not re.search(r"\.[a-z]{2,}$", host)
            ):
                return None
        else:
            if not address.is_global:
                return None
    except ValueError:
        return None
    return value


def prompt_public_urls(text, *, limit=MAX_PAGES):
    found, seen = [], set()
    if not isinstance(text, str):
        return found
    for match in PROMPT_URL.findall(text):
        url = public_url(match.rstrip(".,;:)]}"))
        if not url or url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) == limit:
            break
    return found


def reviewed_urls(values):
    if values in (None, []):
        return []
    if not isinstance(values, list) or len(values) > MAX_PAGES:
        raise ValueError("http_fetch accepts at most three public URLs")
    found, seen = [], set()
    for item in values:
        text = item.strip() if isinstance(item, str) else ""
        url = public_url(text)
        if not url:
            raise ValueError("http_fetch requires public http(s) URLs on port 80 or 443")
        if url in seen:
            raise ValueError("Duplicate fetch URLs are not allowed")
        seen.add(url)
        found.append(url)
    return found


async def public_addresses(host):
    try:
        rows = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("URL host could not be resolved") from exc
    addresses = []
    for row in rows:
        address = ipaddress.ip_address(row[4][0])
        if not address.is_global:
            raise ValueError("Refusing a non-public network address")
        addresses.append(str(address))
    if not addresses:
        raise ValueError("URL host could not be resolved")
    return addresses


async def fetch_public(url):
    current = public_url(url)
    if not current:
        raise ValueError("http_fetch requires a public http(s) URL")
    headers = {
        "User-Agent": "AI-Station-agent/1",
        "Accept": "text/html,application/xhtml+xml,text/plain,application/json,text/markdown;q=0.9,*/*;q=0.1",
    }
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, trust_env=False, follow_redirects=False, headers=headers
        ) as client:
            async with asyncio.timeout(TIMEOUT + 2):
                for _ in range(MAX_REDIRECTS + 1):
                    host = urlsplit(current).hostname
                    if not host:
                        raise ValueError("http_fetch requires a public http(s) URL")
                    await public_addresses(host)
                    async with client.stream("GET", current) as response:
                        if response.status_code in REDIRECTS:
                            location = response.headers.get("location")
                            nxt = public_url(urljoin(current, location)) if location else None
                            if not nxt:
                                raise ValueError("Redirect targeted a non-public URL")
                            current = nxt
                            continue
                        content_type = response.headers.get("content-type", "")
                        body = bytearray()
                        truncated = False
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BODY:
                                del body[MAX_BODY:]
                                truncated = True
                                break
                        return _excerpt(current, response.status_code, content_type, bytes(body), truncated)
                raise ValueError("Too many redirects")
    except ValueError:
        raise
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise ProviderError("HTTP fetch could not complete. Check the URL and try again.") from exc


async def execute_fetch(session, run, urls, *, deadline=None):
    if "network_read" not in run.effective_permissions:
        raise ProviderError("HTTP fetch requires explicit network permission")
    try:
        pages_spec = reviewed_urls(urls)
    except ValueError as exc:
        raise ProviderError(str(exc)) from exc
    if not pages_spec:
        raise ProviderError("http_fetch requires 1 to 3 explicit public URLs")
    append_event(session, run.id, "tool.requested", {"tool": "http_fetch", "urls": pages_spec})
    append_event(session, run.id, "tool.started", {"tool": "http_fetch"})
    session.commit()
    pages = []
    try:
        for url in pages_spec:
            pending = asyncio.create_task(fetch_public(url))
            try:
                while True:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise ProviderError("Agent runtime limit exceeded during HTTP fetch")
                    session.refresh(run)
                    canceled = run.status == "cancel_requested"
                    session.commit()
                    if canceled:
                        append_event(session, run.id, "tool.canceled", {"tool": "http_fetch"})
                        return None
                    ready, _ = await asyncio.wait([pending], timeout=0.2)
                    if ready:
                        pages.append(pending.result())
                        break
            finally:
                if not pending.done():
                    pending.cancel()
                    with suppress(asyncio.CancelledError):
                        await pending
        result = {"urls": pages_spec, "fetched_at": utcnow().isoformat(), "pages": pages}
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(result, handle)
            handle.flush()
            artifact = register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="http-fetch.json",
                run_id=run.id,
                metadata={"tool": "http_fetch"},
            )
        result = {**result, "artifact_id": artifact.id}
        run.metadata_json = {**run.metadata_json, "http_fetch": result}
        append_event(
            session,
            run.id,
            "tool.completed",
            {"tool": "http_fetch", "page_count": len(pages), "artifact_id": artifact.id},
        )
        session.commit()
        return result
    except (ProviderError, ValueError) as exc:
        error = str(exc) if isinstance(exc, ProviderError) else str(exc)
        append_event(session, run.id, "tool.failed", {"tool": "http_fetch", "error": error})
        if isinstance(exc, ValueError):
            raise ProviderError(error) from exc
        raise
    finally:
        session.commit()


def _excerpt(url, status, content_type, body, truncated):
    ctype = (content_type or "").split(";")[0].strip().lower()
    result = {
        "url": url,
        "status": status,
        "content_type": ctype,
        "text": "",
        "links": [],
        "truncated": truncated,
        "untrusted": True,
        "bounded": True,
    }
    if status < 200 or status >= 300:
        result["error"] = f"HTTP {status}"
        return result
    if ctype.startswith(BINARY_PREFIXES) or ctype in BINARY_TYPES:
        result["skipped"] = "binary"
        return result
    text = body.decode("utf-8", errors="replace")
    if "html" in ctype or _looks_like_html(text):
        result["text"], result["links"] = _html_excerpt(text, url)
    else:
        result["text"] = text[:MAX_TEXT]
        if len(text) > MAX_TEXT:
            result["truncated"] = True
    return result


def _looks_like_html(text):
    start = text.lstrip()[:32].lower()
    return start.startswith("<!doctype html") or start.startswith("<html")


def _html_excerpt(text, url):
    cleaned = re.sub(r"(?is)<(script|style|noscript)\b.*?>.*?</\1>", " ", text)
    links, seen = [], set()
    origin = urlsplit(url)
    for href in re.findall(r'(?is)href\s*=\s*["\']([^"\']+)["\']', cleaned):
        absolute = public_url(urljoin(url, unescape(href.strip())))
        if not absolute or absolute in seen:
            continue
        if urlsplit(absolute).hostname != origin.hostname:
            continue
        seen.add(absolute)
        links.append(absolute)
        if len(links) == MAX_LINKS:
            break
    return _plain(cleaned, MAX_TEXT), links


def _plain(value, limit):
    text = unescape(re.sub(r"<[^>]*>", " ", value if isinstance(value, str) else ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]
