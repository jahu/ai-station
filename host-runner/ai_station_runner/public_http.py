"""Public GET and configured search for local coding. No browser or private SSRF."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlsplit

import httpx

from ai_station_runner.config import get_settings

MAX_URL = 2000
MAX_BODY = 256 * 1024
MAX_TEXT = 8_000
MAX_REDIRECTS = 3
MAX_LINKS = 15
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


PROMPT_URL = re.compile(r"https?://[^\s)\]>'\"<>]+", re.IGNORECASE)


def prompt_public_urls(text, *, limit=3):
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


def proposal_references(observations):
    refs = []
    if not isinstance(observations, list):
        return refs
    for item in observations:
        if not isinstance(item, dict):
            continue
        request, result = item.get("request") or {}, item.get("result") or {}
        if not isinstance(request, dict) or not isinstance(result, dict):
            continue
        if request.get("tool") == "fetch_url":
            text = result.get("text")
            if isinstance(text, str) and text.strip():
                refs.append(
                    {
                        "url": result.get("url") or request.get("url"),
                        "text": text[:MAX_TEXT],
                        "untrusted": True,
                    }
                )
        elif request.get("tool") == "web_search":
            sources = result.get("sources")
            if isinstance(sources, list) and sources:
                refs.append(
                    {
                        "query": result.get("query"),
                        "sources": sources[:5],
                        "untrusted": True,
                    }
                )
        if len(refs) == 6:
            break
    return refs


def public_addresses(host):
    try:
        rows = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
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


def configured_search_url():
    endpoint = (get_settings().web_search_url or "").strip().rstrip("/")
    if not endpoint or len(endpoint) > MAX_URL:
        return ""
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname:
        return ""
    return endpoint


def fetch_public(url):
    current = public_url(url)
    if not current:
        raise ValueError("fetch_url requires a public http(s) URL")
    headers = {
        "User-Agent": "AI-Station-local-coding/1",
        "Accept": "text/html,application/xhtml+xml,text/plain,application/json,text/markdown;q=0.9,*/*;q=0.1",
    }
    try:
        with httpx.Client(
            timeout=TIMEOUT, trust_env=False, follow_redirects=False, headers=headers
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                host = urlsplit(current).hostname
                if not host:
                    raise ValueError("fetch_url requires a public http(s) URL")
                public_addresses(host)
                with client.stream("GET", current) as response:
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
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            del body[MAX_BODY:]
                            truncated = True
                            break
                    return _excerpt(current, response.status_code, content_type, bytes(body), truncated)
            return {
                "url": current,
                "error": "Too many redirects",
                "untrusted": True,
                "bounded": True,
            }
    except ValueError:
        raise
    except (httpx.HTTPError, TimeoutError, OSError):
        return {"url": current, "error": "Fetch could not complete", "untrusted": True, "bounded": True}


def search_web(query):
    endpoint = configured_search_url()
    if not endpoint:
        raise ValueError("Web search is not configured")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
        raise ValueError("web_search requires a query between 1 and 500 characters")
    query = query.strip()
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            with client.stream(
                "POST",
                endpoint + "/search",
                data={"q": query, "format": "json", "categories": "general"},
            ) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise ValueError("Search response exceeded its size limit")
        payload = json.loads(bytes(content))
        rows = payload.get("results")
        if not isinstance(rows, list):
            raise ValueError("Invalid search results")
        sources, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = public_url(row.get("url"))
            if not url or url in seen:
                continue
            title = _plain(row.get("title"), 200)
            if not title:
                continue
            sources.append(
                {
                    "id": len(sources) + 1,
                    "title": title,
                    "url": url,
                    "snippet": _plain(row.get("content"), 700),
                }
            )
            seen.add(url)
            if len(sources) == 5:
                break
        return {
            "query": query,
            "provider": "searxng",
            "sources": sources,
            "partial": bool(payload.get("unresponsive_engines")),
            "untrusted": True,
            "bounded": True,
        }
    except ValueError:
        raise
    except (httpx.HTTPError, TimeoutError, OSError, json.JSONDecodeError, TypeError):
        return {"query": query, "error": "Web search could not complete", "untrusted": True, "bounded": True}


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
