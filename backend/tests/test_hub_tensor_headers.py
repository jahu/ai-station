"""Publisher tensor-state metadata remains bounded and never reads raw weights."""

import asyncio
import hashlib
import io
import struct
import zipfile
from contextlib import asynccontextmanager

import httpx
import pytest
from ai_station_runner.torch_state_zip import read_archive
from app import hub_checkpoint_headers as transport
from app import hub_tensor_headers as headers


def source(*, metadata=None, compressed=False, extra=None):
    # Primitive protocol-2 fixture with one complete detached contiguous tensor.
    def text(value):
        raw = value.encode()
        return b"X" + struct.pack("<I", len(raw)) + raw

    raw = metadata or (
        b"\x80\x02}"
        + text("weight")
        + b"ctorch._utils\n_rebuild_tensor_v2\n(("
        + text("storage")
        + b"ctorch\nFloatStorage\n"
        + text("0")
        + text("cuda:0")
        + b"K\x02tQK\x00K\x02\x85K\x01\x85\x89}tRs."
    )
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        rows = {
            "data.pkl": raw,
            "byteorder": b"little",
            "version": b"3\n",
            "data/0": struct.pack("<ff", 1.25, -2.5),
        }
        if extra:
            rows[extra] = b"unsupported"
        for name, content in rows.items():
            name = "weights/" + name
            item = zipfile.ZipInfo(name)
            padding = (-(target.tell() + 30 + len(name) + 4)) % 64
            item.extra = struct.pack("<HH", 0x4246, padding) + b"Z" * padding
            item.compress_type = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
            archive.writestr(item, content)
    content = target.getvalue()
    return {
        "filename": "unet.pth",
        "identity_available": True,
        "format": "pth",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "source_url": "https://huggingface.co/publisher/model/resolve/" + "a" * 40 + "/unet.pth",
    }, content


def bridge(monkeypatch, *, file=None, content=None, status=206, corrupt=None):
    if file is None:
        file, content = source()
    calls = []

    @asynccontextmanager
    async def response(url, begin, check, *, end):
        check()
        calls.append((begin, end))
        body = content[begin : end + 1]
        values = {
            "content-range": f"bytes {begin}-{end}/{file['size_bytes']}",
            "content-length": str(len(body)),
        }
        if corrupt:
            values.update(corrupt)
        reply = httpx.Response(
            status, headers=values, stream=httpx.ByteStream(body), request=httpx.Request("GET", url)
        )
        try:
            yield reply
        finally:
            await reply.aclose()

    monkeypatch.setattr(transport, "response", response)
    return file, content, calls


def test_full_graph_metadata_matches_native_without_requesting_any_tensor_storage(monkeypatch):
    file, content, calls = bridge(monkeypatch)
    native = read_archive(io.BytesIO(content))
    report = asyncio.run(headers.inspect(file, lambda: None))
    for key in (
        "schema_sha256",
        "module_metadata_sha256",
        "header_sha256",
        "tensor_count",
        "dtypes",
        "tensor_storage_bytes",
    ):
        assert report[key] == native["report"][key]
    for tensor in native["tensors"]:
        low, high = tensor["data_offset"], tensor["data_offset"] + tensor["size_bytes"]
        assert all(not (begin < high and end + 1 > low) for begin, end in calls)
    assert report["metadata_requests"] == len(calls) == 5
    assert report["metadata_transfer_bytes"] == sum(end - begin + 1 for begin, end in calls)
    assert not report["storage_layout_verified"] and not report["runtime_qualified"]


@pytest.mark.parametrize(
    "status,corrupt",
    [(200, None), (206, {"content-encoding": "gzip"}), (206, {"content-range": "bytes 0-7/999"})],
)
def test_server_cannot_turn_metadata_inspection_into_a_complete_download(monkeypatch, status, corrupt):
    file, _, calls = bridge(monkeypatch, status=status, corrupt=corrupt)
    with pytest.raises(ValueError, match="exact bounded"):
        asyncio.run(headers.inspect(file, lambda: None))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"source_url": "https://huggingface.co/publisher/model/resolve/main/unet.pth"},
        {"source_url": "http://127.0.0.1/model"},
        {"size_bytes": 2},
        {"size_bytes": headers.MAX_FILE + 1},
        {"format": "gguf"},
        {"identity_available": False},
    ],
)
def test_nonimmutable_or_incompatible_sources_fail_before_network(monkeypatch, change):
    file, _, calls = bridge(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(headers.inspect({**file, **change}, lambda: None))
    assert not calls


@pytest.mark.parametrize("case", ["compressed", "code", "executable", "trailer", "overlap"])
def test_malformed_archive_or_executable_metadata_never_grants_model_support(monkeypatch, case):
    file, content = source(
        compressed=case == "compressed",
        extra="code/forward.py" if case == "code" else None,
        metadata=b"\x80\x02cos\nsystem\n)R." if case == "executable" else None,
    )
    if case == "trailer":
        content += b"bad"
    if case == "overlap":
        offset = content.index(b"PK\x01\x02", content.index(b"PK\x01\x02") + 1)
        modified = bytearray(content)
        modified[offset + 42 : offset + 46] = b"\0" * 4
        content = bytes(modified)
    file["size_bytes"] = len(content)
    file, _, calls = bridge(monkeypatch, file=file, content=content)
    with pytest.raises(ValueError):
        asyncio.run(headers.inspect(file, lambda: None))
    assert len(calls) <= headers.MAX_REQUESTS


def test_cancellation_stops_before_another_range(monkeypatch):
    file, _, calls = bridge(monkeypatch)

    class Stopped(Exception):
        pass

    def check():
        if len(calls) >= 1:
            raise Stopped()

    with pytest.raises(Stopped):
        asyncio.run(headers.inspect(file, check))
    assert len(calls) == 1


def test_sparse_view_has_no_hidden_network_or_unbounded_payload_read():
    view = headers.MetadataView(1000)
    view.add(20, b"known")
    view.seek(20)
    assert view.read(5) == b"known"
    with pytest.raises(ValueError):
        view.read(1)
    with pytest.raises(ValueError):
        view.read()
    with pytest.raises(ValueError):
        view.seek(1001)


def test_metadata_read_budget_cannot_be_increased_by_directory_entries(monkeypatch):
    file, _, calls = bridge(monkeypatch)
    monkeypatch.setattr(headers, "MAX_REQUESTS", 2)
    with pytest.raises(ValueError, match="fixed budget"):
        asyncio.run(headers.inspect(file, lambda: None))
    assert len(calls) == 2
