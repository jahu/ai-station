"""Pinned app-owned model files: resumable HTTPS, verified bytes, atomic publication.

Only reviewed catalog recipes may construct FileSpec. This is not a caller-URL
API or a runtime installer; no downloaded code is imported or executed.
"""

import asyncio
import fcntl
import hashlib
import os
import re
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.http_fetch import pinned_request, public_addresses, public_url

CHUNK = 1024 * 1024
RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")


class FileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(ge=1, le=256 * 1024**3)
    urls: tuple[str, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def reviewed_https(self):
        if any(
            not public_url(url) or urlsplit(url).scheme != "https" or urlsplit(url).fragment
            for url in self.urls
        ):
            raise ValueError("Catalog files require public HTTPS sources without credentials or fragments")
        return self


class DownloadBusy(Exception):
    pass


class SourceUnavailable(Exception):
    pass


class VerificationFailed(ValueError):
    pass


def _file(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o022
    ):
        os.close(fd)
        raise ValueError(
            "Model storage requires owned regular files without hard links or group/world write access"
        )
    return fd


def directory(root):
    root = Path(root).resolve(strict=True)
    result = root
    for name in ("models", "store"):
        result = result / name
        if result.is_symlink():
            raise ValueError("Model storage cannot cross symlinks")
        result.mkdir(mode=0o700, exist_ok=True)
        if not result.is_dir():
            raise ValueError("Model storage requires a directory")
    return result


def verify(path, spec, check):
    digest = hashlib.sha256()
    with os.fdopen(_file(path, os.O_RDONLY), "rb") as source:
        if os.fstat(source.fileno()).st_size != spec.size_bytes:
            raise VerificationFailed("The stored model size differs from the reviewed catalog file")
        while chunk := source.read(4 * CHUNK):
            check()
            digest.update(chunk)
    if digest.hexdigest() != spec.sha256:
        raise VerificationFailed("The model hash differs from the reviewed catalog file")


async def _wait(check, awaitable, seconds):
    pending = asyncio.ensure_future(awaitable)
    try:
        async with asyncio.timeout(seconds):
            while True:
                check()
                ready, _ = await asyncio.wait([pending], timeout=0.2)
                if ready:
                    check()
                    return pending.result()
    finally:
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass


@asynccontextmanager
async def response(url, offset, check):
    """Revalidate and pin public DNS at every redirect; never follow implicitly."""
    for _ in range(7):
        check()
        parsed = urlsplit(url)
        if not public_url(url) or parsed.scheme != "https" or parsed.fragment:
            raise ValueError("Model sources and redirects must use public HTTPS")
        addresses = await _wait(check, public_addresses(parsed.hostname), 20)
        target, headers, extensions = pinned_request(url, addresses[0])
        headers = {**headers, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10), trust_env=False, follow_redirects=False
        ) as client:
            result = await _wait(
                check,
                client.send(
                    client.build_request("GET", target, headers=headers, extensions=extensions), stream=True
                ),
                35,
            )
            try:
                if result.is_redirect:
                    url = urljoin(url, result.headers.get("location", ""))
                    continue
                yield result
                return
            finally:
                await result.aclose()
    raise ValueError("Model source redirected too many times")


def _position(result, offset, spec):
    if result.status_code in {403, 404, 410}:
        raise SourceUnavailable("The reviewed model source is unavailable")
    result.raise_for_status()
    if result.headers.get("content-encoding", "identity").lower() != "identity":
        raise ValueError("Model byte ranges require identity encoding")
    if result.status_code == 200:
        offset = 0  # A server without Range support must never append a full file.
    elif result.status_code == 206:
        match = RANGE.fullmatch(result.headers.get("content-range", ""))
        if not match or tuple(map(int, match.groups())) != (offset, spec.size_bytes - 1, spec.size_bytes):
            raise ValueError("The model source returned an inconsistent byte range")
    else:
        raise ValueError("The model source did not return file bytes")
    length = result.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) != spec.size_bytes - offset):
        raise ValueError("Model response size differs from the reviewed catalog file")
    return offset


async def _transfer(url, partial, spec, check, progress):
    with os.fdopen(_file(partial, os.O_RDWR | os.O_CREAT), "r+b") as output:
        offset = os.fstat(output.fileno()).st_size
        if offset > spec.size_bytes:
            raise ValueError("The saved model partial exceeds its reviewed size")
        if offset == spec.size_bytes:
            return
        async with response(url, offset, check) as result:
            offset = _position(result, offset, spec)
            output.seek(offset)
            output.truncate(offset)
            total, previous = offset, offset
            chunks = result.aiter_raw(chunk_size=CHUNK).__aiter__()
            progress(total, spec.size_bytes)
            try:
                while True:
                    try:
                        chunk = await _wait(check, anext(chunks), 40)
                    except StopAsyncIteration:
                        break
                    if total + len(chunk) > spec.size_bytes:
                        raise ValueError("Model download exceeds its reviewed size")
                    output.write(chunk)
                    total += len(chunk)
                    if total - previous >= 4 * CHUNK:
                        progress(total, spec.size_bytes)
                        previous = total
                if total != spec.size_bytes:
                    raise SourceUnavailable("The model transfer ended early; its partial is retained")
                progress(total, spec.size_bytes)
            finally:
                output.flush()
                os.fsync(output.fileno())


async def obtain(
    root: Path, spec: FileSpec, *, check: Callable[[], None], progress: Callable[[int, int], None]
) -> Path:
    """Retrieve one reviewed object; cancellation retains only unpublished partials.

    The caller supplies the durable Run cancellation/deadline check and event
    recorder. No caller selects an output path, alters a model or receives a
    successful installed state before full byte/hash verification.
    """
    folder = directory(root)
    final = folder / spec.sha256
    partial = folder / (spec.sha256 + ".part")
    lock = _file(folder / (spec.sha256 + ".lock"), os.O_RDWR | os.O_CREAT)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DownloadBusy("This model is already being prepared") from exc
        check()
        if final.exists() or final.is_symlink():
            # Recover only our interrupted link-before-unlink publication.
            if not final.is_symlink() and not partial.is_symlink() and partial.exists():
                a, b = final.stat(), partial.stat()
                if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) and a.st_nlink == 2:
                    partial.unlink()
            verify(final, spec, check)
            os.chmod(final, 0o444, follow_symlinks=False)
            return final
        last_error = None
        for url in spec.urls:
            try:
                await _transfer(url, partial, spec, check, progress)
                verify(partial, spec, check)
                check()
                # Create without overwriting any existing model or symlink.
                os.link(partial, final, follow_symlinks=False)
                os.chmod(final, 0o444, follow_symlinks=False)
                partial.unlink()
                directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                return final
            except VerificationFailed as exc:
                # Discard only our bad unpublished bytes, never an installed model.
                with os.fdopen(_file(partial, os.O_RDWR), "r+b") as invalid:
                    invalid.truncate(0)
                    invalid.flush()
                    os.fsync(invalid.fileno())
                last_error = exc
            except (httpx.HTTPError, TimeoutError, SourceUnavailable) as exc:
                last_error = exc
        raise SourceUnavailable(
            "No reviewed model source completed; retry to resume the saved partial"
        ) from last_error
    finally:
        os.close(lock)
