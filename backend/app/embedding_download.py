"""Explicit pinned model preparation; public DNS-pinned HTTPS and atomic files."""

import asyncio
import hashlib
import os
from urllib.parse import urljoin, urlsplit

import httpx

from app.embedding_models import (
    FILES,
    REPOSITORY,
    REVISION,
    directory,
    model_file,
    verify_file,
    write_receipt,
)
from app.embedding_process import check_running, wait_running
from app.events import append_event
from app.http_fetch import pinned_request, public_addresses, public_url
from app.providers import ProviderError


async def download_file(session, run, root, name):
    spec = FILES[name]
    initial = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{spec['remote']}"
    current = initial
    temporary = directory(root, create=True) / (run.id + "-" + name + ".part")
    pending = None
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            async with asyncio.timeout(300):
                for _ in range(7):
                    check_running(session, run)
                    host = urlsplit(current).hostname
                    if not host or not current.startswith("https://") or not public_url(current):
                        raise ValueError("Model download must use public HTTPS")
                    addresses = await wait_running(session, run, public_addresses(host), seconds=20)
                    target, headers, extensions = pinned_request(current, addresses[0])
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(20, connect=10), trust_env=False, follow_redirects=False
                    ) as client:
                        response = await wait_running(
                            session,
                            run,
                            client.send(
                                client.build_request("GET", target, headers=headers, extensions=extensions),
                                stream=True,
                            ),
                            seconds=30,
                        )
                        try:
                            if response.is_redirect:
                                current = urljoin(current, response.headers.get("location", ""))
                                continue
                            response.raise_for_status()
                            length = response.headers.get("content-length")
                            if length and (not length.isdigit() or int(length) != spec["size"]):
                                raise ValueError("Model download length differs from the pinned file")
                            digest, total, last_event = hashlib.sha256(), 0, 0
                            chunks = response.aiter_bytes(chunk_size=1024 * 1024).__aiter__()
                            try:
                                while True:
                                    if pending is None:
                                        pending = asyncio.create_task(anext(chunks))
                                    check_running(session, run)
                                    ready, _ = await asyncio.wait([pending], timeout=0.2)
                                    if not ready:
                                        continue
                                    try:
                                        chunk = pending.result()
                                    except StopAsyncIteration:
                                        break
                                    finally:
                                        pending = None
                                    total += len(chunk)
                                    if total > spec["size"]:
                                        raise ValueError("Model download exceeds its pinned size")
                                    output.write(chunk)
                                    digest.update(chunk)
                                    if total - last_event >= 4 * 1024 * 1024:
                                        run.metadata_json = {
                                            **run.metadata_json,
                                            "embedding_download": {
                                                "file": name,
                                                "received_bytes": total,
                                                "expected_bytes": spec["size"],
                                            },
                                        }
                                        append_event(
                                            session,
                                            run.id,
                                            "embedding.download.progress",
                                            {
                                                "file": name,
                                                "received_bytes": total,
                                                "expected_bytes": spec["size"],
                                            },
                                        )
                                        session.commit()
                                        last_event = total
                            finally:
                                if pending is not None and not pending.done():
                                    pending.cancel()
                                    try:
                                        await pending
                                    except asyncio.CancelledError:
                                        pass
                                    pending = None
                            if total != spec["size"] or digest.hexdigest() != spec["sha256"]:
                                raise ValueError("Model download failed byte/hash verification")
                            output.flush()
                            os.fsync(output.fileno())
                            check_running(session, run)
                            temporary.replace(model_file(root, name))
                            append_event(
                                session,
                                run.id,
                                "embedding.download.verified",
                                {"file": name, "size_bytes": total, "sha256": spec["sha256"]},
                            )
                            session.commit()
                            return
                        finally:
                            await response.aclose()
                raise ValueError("Model download redirected too many times")
    except httpx.HTTPError as exc:
        raise ProviderError(
            "Embedding model download failed. Check connectivity and try preparation again."
        ) from exc
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
        temporary.unlink(missing_ok=True)


async def prepare_files(session, run, root, *, allow_download):
    directory(root, create=True)
    for name in FILES:
        check_running(session, run)
        try:
            verify_file(root, name)
            continue
        except (OSError, ValueError):
            if not allow_download:
                raise ValueError(
                    "Explicitly confirm the embedding model download before preparing missing files"
                )
        append_event(
            session, run.id, "embedding.download.started", {"file": name, "size_bytes": FILES[name]["size"]}
        )
        session.commit()
        await download_file(session, run, root, name)
    check_running(session, run)
    return write_receipt(root)
