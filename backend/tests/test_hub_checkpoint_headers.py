"""Exact bounded publisher metadata ranges never consume model tensor bytes."""

import asyncio
import json
import struct
from contextlib import asynccontextmanager

import httpx
import pytest
from app import hub_checkpoint_headers as headers


def source():
    raw = json.dumps({"weight": {"dtype": "F16", "shape": [2], "data_offsets": [0, 4]}}).encode()
    content = struct.pack("<Q", len(raw)) + raw + bytes(4)
    file = {
        "filename": "model.safetensors",
        "identity_available": True,
        "format": "safetensors",
        "size_bytes": len(content),
        "sha256": "b" * 64,
        "source_url": "https://huggingface.co/publisher/model/resolve/" + "a" * 40 + "/model.safetensors",
    }
    return file, raw, content


def bridge(monkeypatch, *, status=206, corrupt=None):
    file, raw, content = source()
    calls, consumed = [], []

    @asynccontextmanager
    async def response(url, offset, check, *, end):
        check()
        calls.append((url, offset, end))
        assert end < len(content) - 4  # No tensor payload in either requested range.
        body = content[offset : end + 1]
        values = {
            "content-range": f"bytes {offset}-{end}/{file['size_bytes']}",
            "content-length": str(len(body)),
        }
        if corrupt:
            values.update(corrupt)
        consumed.append(len(body) if status == 206 and not corrupt else 0)
        answer = httpx.Response(
            status, headers=values, stream=httpx.ByteStream(body), request=httpx.Request("GET", url)
        )
        try:
            yield answer
        finally:
            await answer.aclose()

    monkeypatch.setattr(headers, "response", response)
    return file, raw, content, calls, consumed


def test_only_length_and_header_ranges_are_requested_and_frozen(monkeypatch):
    file, raw, content, calls, consumed = bridge(monkeypatch)
    report = asyncio.run(headers.inspect(file, lambda: None))
    assert [(a, b) for _, a, b in calls] == [(0, 7), (8, len(content) - 5)]
    assert sum(consumed) == report["header_bytes"] == 8 + len(raw)
    assert report["tensor_count"] == 1 and report["dtypes"] == ["F16"]


@pytest.mark.parametrize(
    "status,corrupt",
    [
        (200, None),
        (403, None),
        (206, {"content-range": "bytes 0-7/999"}),
        (206, {"content-length": "999"}),
        (206, {"content-encoding": "gzip"}),
    ],
)
def test_ignored_range_or_changed_metadata_is_not_a_permission_to_download_weights(
    monkeypatch, status, corrupt
):
    file, _, _, calls, _ = bridge(monkeypatch, status=status, corrupt=corrupt)
    with pytest.raises(ValueError, match="exact bounded"):
        asyncio.run(headers.inspect(file, lambda: None))
    assert len(calls) == 1


def test_unbounded_or_nonimmutable_sources_are_rejected_before_transport(monkeypatch):
    file, _, _, calls, _ = bridge(monkeypatch)
    for change in (
        {"source_url": "https://huggingface.co/publisher/model/resolve/main/model.safetensors"},
        {"source_url": "https://127.0.0.1/model"},
        {"size_bytes": 1},
        {"format": "pt"},
        {"identity_available": False},
    ):
        with pytest.raises(ValueError):
            asyncio.run(headers.inspect({**file, **change}, lambda: None))
    assert not calls


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":{},"x":{}}',
        b'{"x":{"dtype":"F16","shape":[true],"data_offsets":[0,2]}}',
        b'{"__metadata__":{"x":"\\ud800"}}',
        b'{"x":{"dtype":"F16","shape":[2],"data_offsets":[1,5]}}',
    ],
)
def test_ambiguous_graph_storage_or_unicode_cannot_form_a_plan(raw):
    with pytest.raises(ValueError):
        headers.describe(raw, len(raw) + 12)


def test_stop_during_metadata_read_propagates_without_fetching_the_next_range(monkeypatch):
    file, _, _, calls, _ = bridge(monkeypatch)
    count = 0

    class Stopped(Exception):
        pass

    def check():
        nonlocal count
        count += 1
        if count >= 3:
            raise Stopped()

    with pytest.raises(Stopped):
        asyncio.run(headers.inspect(file, check))
    assert len(calls) == 1
