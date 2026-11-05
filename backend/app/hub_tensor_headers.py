"""Closed HF tensor ZIP metadata ranges, never a checkpoint download or loader."""

import io
import struct
import zipfile

from ai_station_runner.torch_state_zip import (
    MAX_DIRECTORY,
    MAX_FILE,
    MAX_METADATA,
    directory_end,
    metadata_ranges,
    read_archive,
)

from app.hub_checkpoint_headers import read_range

MAX_REQUESTS = 8  # Tail, directory and at most six fixed metadata entries.
MAX_BYTES = MAX_DIRECTORY + MAX_METADATA + 128 + 6 * 8192


class MetadataView(io.RawIOBase):
    """Sparse seekable data with no network or ability to read storage gaps."""

    def __init__(self, size):
        self.size = size
        self.position = 0
        self.chunks = []

    def add(self, begin, raw):
        self.chunks.append((begin, begin + len(raw), raw))

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if whence not in {0, 1, 2} or not 0 <= position <= self.size:
            raise ValueError("Tensor metadata seek exceeds its range")
        self.position = position
        return position

    def read(self, count=-1):
        if count == -1:
            count = self.size - self.position
        if type(count) is not int or not 0 <= count <= MAX_BYTES:
            raise ValueError("Unbounded tensor metadata reads are forbidden")
        end = min(self.size, self.position + count)
        if end == self.position:
            return b""
        for begin, stop, raw in self.chunks:
            if begin <= self.position and end <= stop:
                value = raw[self.position - begin : end - begin]
                self.position = end
                return value
        raise ValueError("Tensor payload and unobserved archive ranges cannot be read")


async def inspect(file, check):
    size = file.get("size_bytes")
    if (
        not file.get("identity_available")
        or file.get("format") not in {"pth", "pt", "bin"}
        or type(size) is not int
        or not 128 <= size <= MAX_FILE
    ):
        raise ValueError("Choose one immutable supported tensor ZIP checkpoint")
    view, requests, transferred = MetadataView(size), 0, 0

    async def fetch(begin, end):
        nonlocal requests, transferred
        length = end - begin + 1
        if not 0 <= begin <= end < size or requests >= MAX_REQUESTS or transferred + length > MAX_BYTES:
            raise ValueError("Tensor metadata transfer exceeds its fixed budget")
        check()
        raw = await read_range(file, begin, end, check)
        if len(raw) != length:
            raise ValueError("Truncated tensor metadata range")
        view.add(begin, raw)
        requests += 1
        transferred += length
        check()
        return raw

    try:
        tail = await fetch(size - 128, size - 1)
        offset, length, _ = directory_end(tail, size)
        await fetch(offset, offset + length - 1)
        ranges = metadata_ranges(view)
        for begin, end in ranges:
            await fetch(begin, end)
        check()
        report = read_archive(view, verify_local=False)["report"]
        check()
    except (zipfile.BadZipFile, NotImplementedError, UnicodeError, struct.error) as exc:
        raise ValueError("Unsupported or invalid closed tensor archive") from exc
    return {**report, "metadata_transfer_bytes": transferred, "metadata_requests": requests}
