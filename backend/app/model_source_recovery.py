"""Locate the same reviewed HF object at another immutable publisher revision.

Metadata is a locator hint, never authority to change the expected file bytes.
The caller supplies its existing pinned HTTPS transport and durable Run checks.
"""

import json
import re
from urllib.parse import quote, unquote, urlsplit

import httpx

MAX_METADATA_BYTES = 1024 * 1024
REVISION = re.compile(r"[a-f0-9]{40}\Z")
REPO_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")


class InvalidMetadata(ValueError):
    pass


def source_identity(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc != "huggingface.co" or parsed.query or parsed.fragment:
        return None
    try:
        parts = unquote(parsed.path, errors="strict").split("/")
    except UnicodeError:
        return None
    if (
        len(parts) < 6
        or parts[0]
        or not REPO_PART.fullmatch(parts[1])
        or not REPO_PART.fullmatch(parts[2])
        or parts[3] != "resolve"
        or not REVISION.fullmatch(parts[4])
        or len(parsed.path) > 2048
        or re.search(r"%2f|%5c", parsed.path, flags=re.IGNORECASE)
        or any(part in {"", ".", ".."} for part in parts[1:])
        or any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in parsed.path)
        or any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in "/".join(parts))
    ):
        return None
    return "/".join(parts[1:3]), parts[4], "/".join(parts[5:])


async def _metadata(repository, *, check, response, wait):
    url = f"https://huggingface.co/api/models/{repository}/revision/main?blobs=true"
    async with response(url, 0, check) as result:
        result.raise_for_status()
        if (
            result.status_code != 200
            or result.headers.get("content-encoding", "identity").lower() != "identity"
        ):
            raise InvalidMetadata("Model source metadata must be uncompressed JSON")
        length = result.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_METADATA_BYTES):
            raise InvalidMetadata("Model source metadata exceeds its limit")
        data = bytearray()
        chunks = result.aiter_raw(chunk_size=64 * 1024).__aiter__()
        while True:
            try:
                chunk = await wait(check, anext(chunks), 35)
            except StopAsyncIteration:
                break
            if len(data) + len(chunk) > MAX_METADATA_BYTES:
                raise InvalidMetadata("Model source metadata exceeds its limit")
            data.extend(chunk)
        check()
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise InvalidMetadata("Model source metadata is not bounded valid JSON") from exc


def equivalent_url(metadata, identity, spec):
    repository, old_revision, filename = identity
    if not isinstance(metadata, dict):
        return None
    revision, siblings = metadata.get("sha"), metadata.get("siblings")
    if (
        not isinstance(revision, str)
        or not REVISION.fullmatch(revision)
        or revision == old_revision
        or not isinstance(siblings, list)
        or len(siblings) > 4096
    ):
        return None
    matches = [s for s in siblings if isinstance(s, dict) and s.get("rfilename") == filename]
    if len(matches) != 1:
        return None
    item = matches[0]
    lfs = item.get("lfs")
    if (
        not isinstance(lfs, dict)
        or lfs.get("sha256") != spec.sha256
        or type(lfs.get("size")) is not int
        or lfs["size"] != spec.size_bytes
        or ("size" in item and (type(item["size"]) is not int or item["size"] != spec.size_bytes))
    ):
        return None
    return f"https://huggingface.co/{repository}/resolve/{revision}/{quote(filename, safe='/')}"


async def recover_sources(spec, *, urls, check, response, wait):
    cache, found = {}, []
    for url in urls:
        check()
        if url not in spec.urls:
            continue
        identity = source_identity(url)
        if identity is None:
            continue
        repository = identity[0]
        if repository not in cache:
            try:
                cache[repository] = await _metadata(repository, check=check, response=response, wait=wait)
            except (httpx.HTTPError, TimeoutError, InvalidMetadata):
                cache[repository] = None
        candidate = equivalent_url(cache[repository], identity, spec)
        if candidate is not None and candidate not in spec.urls and candidate not in found:
            found.append(candidate)
    return tuple(found)
