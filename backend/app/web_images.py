"""Bounded public-image discovery/import, using owned artifacts and pinned public DNS."""

import asyncio
import io
import json
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.http_fetch import MAX_REDIRECTS, REDIRECTS, pinned_request, public_addresses, public_url
from app.permissions import require
from app.providers import ProviderError
from app.run_transactions import RunStopped, database_step
from app.runs import touch_lease
from app.state import TERMINAL

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


async def search_images(query):
    endpoint = get_settings().web_search_url.rstrip("/")
    if not endpoint:
        raise ProviderError("Web image search is not configured")
    async with asyncio.timeout(22):
        async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
            async with client.stream(
                "POST", endpoint + "/search", data={"q": query, "format": "json", "categories": "images"}
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("Image search exceeded its response limit")
    payload = json.loads(body)
    sources, seen = [], set()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ProviderError("Image search returned an invalid response")
    for row in payload["results"][:100]:
        if not isinstance(row, dict):
            continue
        url = public_url(row.get("img_src"))
        page = public_url(row.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "url": url,
                "page_url": page,
                "title": str(row.get("title") or "Image reference")[:200],
                "kind": "image",
                "untrusted": True,
            }
        )
        if len(sources) == 5:
            break
    if not sources:
        raise ProviderError(
            "Image search returned no usable images. Try another focused query; no image was invented or downloaded."
        )
    return {
        "query": query,
        "provider": "searxng",
        "category": "images",
        "sources": sources,
        "searched_at": utcnow().isoformat(),
    }


async def download_image(url):
    current = public_url(url)
    if not current:
        raise ValueError("Choose a public image URL on port 80 or 443")
    async with asyncio.timeout(25):
        for _ in range(MAX_REDIRECTS + 1):
            addresses = await public_addresses(urlsplit(current).hostname)
            for index, address in enumerate(addresses):
                try:
                    target, authority, extensions = pinned_request(current, address)
                    async with httpx.AsyncClient(
                        timeout=20,
                        trust_env=False,
                        follow_redirects=False,
                        headers={
                            "User-Agent": "AI-Station/1 (+https://github.com/jahu/ai-station)",
                            "Accept": "image/png,image/jpeg,image/webp",
                        },
                    ) as client:
                        async with client.stream(
                            "GET", target, headers=authority, extensions=extensions
                        ) as response:
                            if response.status_code in REDIRECTS:
                                location = response.headers.get("location")
                                nxt = public_url(urljoin(current, location)) if location else None
                                if not nxt:
                                    raise ValueError("Image redirect targeted a non-public URL")
                                current = nxt
                                break
                            response.raise_for_status()
                            mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                            if mime not in IMAGE_TYPES:
                                raise ValueError("The selected source is not a PNG, JPEG or WebP image")
                            length = response.headers.get("content-length")
                            if length and int(length) > MAX_BYTES:
                                raise ValueError("Web images must be at most 20 MiB")
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                                body.extend(chunk)
                                if len(body) > MAX_BYTES:
                                    raise ValueError("Web image exceeded 20 MiB")
                            return bytes(body), current
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if index == len(addresses) - 1:
                        raise
        raise ValueError("Too many image redirects")


def canonical_image(data, destination):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > MAX_PIXELS:
                raise ValueError("Use a PNG, JPEG or WebP image within 20 megapixels")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Choose a still image as the editing reference")
            image = ImageOps.exif_transpose(image)
            mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            image.convert(mode).save(destination, format="PNG")
            if destination.stat().st_size > MAX_BYTES:
                raise ValueError("The decoded image exceeds 20 MiB")
            return image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The public source did not contain a safe supported image") from exc


async def execute_images(session, run):
    require(run.effective_permissions, "network_read")
    importing = run.parameters["tool"] == "web.image_import"
    if importing:
        require(run.effective_permissions, "workspace_write")
    append_event(session, run.id, "tool.started", {"tool": run.parameters["tool"]})
    session.commit()
    result = {"sources": [], "imported": []} if importing else None
    jobs = run.parameters["urls"] if importing else [run.parameters["arguments"]["query"]]
    claim = run.worker_id, run.claimed_at
    deadline = datetime.fromisoformat(run.parameters["execution_deadline_at"])
    last_lease = monotonic() - 30
    for value in jobs:
        pending = asyncio.create_task(download_image(value) if importing else search_images(value))
        try:
            while True:
                session.refresh(run)
                if (run.worker_id, run.claimed_at) != claim:
                    raise RunStopped("The image retrieval claim changed")
                stopped = run.status == "cancel_requested" or run.status in TERMINAL or utcnow() >= deadline
                if not stopped and monotonic() - last_lease >= max(
                    1, min(10, get_settings().lease_seconds / 3)
                ):
                    touch_lease(session, run)
                    last_lease = monotonic()
                session.commit()
                if stopped:
                    return None
                ready, _ = await asyncio.wait([pending], timeout=0.2)
                if ready:
                    try:
                        data = pending.result()
                    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
                        raise ProviderError("Public image retrieval failed: " + str(exc)[:500]) from exc
                    break
        finally:
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
        if not importing:
            result = data
        else:
            content, final_url = data
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "web-reference.png"
                width, height = canonical_image(content, path)
                artifact_id = str(uuid4())

                def publish():
                    if utcnow() >= deadline:
                        raise RunStopped("The image retrieval deadline expired")
                    return register_file(
                        session,
                        source=path,
                        artifact_type="image",
                        mime_type="image/png",
                        original_filename="web-reference.png",
                        artifact_id=artifact_id,
                        run_id=run.id,
                        metadata={
                            "width": width,
                            "height": height,
                            "operation": "web.image_import",
                            "source_url": value,
                            "resolved_url": final_url,
                            "reference_only": True,
                        },
                    )

                artifact = await database_step(session, run, claim, deadline, publish)
            result["imported"].append(artifact.id)
            result["sources"].append({"url": value, "title": "Imported image reference"})
    append_event(
        session,
        run.id,
        "tool.completed",
        {
            "tool": run.parameters["tool"],
            "image_count": len(result.get("imported", result.get("sources", []))),
        },
    )
    session.commit()
    return result
