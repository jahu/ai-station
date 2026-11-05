"""Closed metadata decoding: test bytes are data, never imported Python objects."""

import io
import pickle
import struct
import zipfile

import pytest
from ai_station_runner import torch_state_data as data
from ai_station_runner import torch_state_zip as archive


def text(value):
    raw = value.encode()
    return b"X" + struct.pack("<I", len(raw)) + raw


def integer(value):
    return b"J" + struct.pack("<i", value)


def metadata(
    *,
    key="weight",
    storage="0",
    shape=(2,),
    stride=(1,),
    offset=0,
    requires_grad=False,
    global_name="torch._utils\n_rebuild_tensor_v2",
    duplicate=False,
    hooks=False,
):
    tensor = (
        b"c"
        + global_name.encode()
        + b"\n("
        + b"("
        + text("storage")
        + b"ctorch\nFloatStorage\n"
        + text(storage)
        + text("cuda:0")
        + integer(2)
        + b"tQ"
        + integer(offset)
        + b"("
        + b"".join(integer(v) for v in shape)
        + b"t"
        + b"("
        + b"".join(integer(v) for v in stride)
        + b"t"
        + (b"\x88" if requires_grad else b"\x89")
        + (b"}" + text("hook") + integer(1) + b"s" if hooks else b"}")
        + b"tR"
    )
    return b"\x80\x02}(" + text(key) + tensor + (text(key) + tensor if duplicate else b"") + b"u."


def checkpoint(*, raw=None, compression=zipfile.ZIP_STORED, extra_file=None):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=compression) as zip:
        rows = {
            "data.pkl": raw if raw is not None else metadata(),
            "byteorder": b"little",
            "version": b"3\n",
            "data/0": struct.pack("<ff", 1.25, -2.5),
        }
        if extra_file:
            rows[extra_file] = b"untrusted"
        for name, content in rows.items():
            name = "weights/" + name
            item = zipfile.ZipInfo(name)
            padding = (-(target.tell() + 30 + len(name.encode()) + 4)) % 64
            item.extra = struct.pack("<HH", 0x4246, padding) + b"Z" * padding
            item.compress_type = compression
            zip.writestr(item, content)
    return target.getvalue()


def test_descriptors_ignore_saved_device_and_never_call_a_pickle_loader(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Input data must never enter an unpickler")

    monkeypatch.setattr(pickle, "load", forbidden)
    monkeypatch.setattr(pickle, "loads", forbidden)
    monkeypatch.setattr(pickle, "Unpickler", forbidden)
    state, versions = data.parse(metadata())
    assert versions == {} and state["weight"].shape == (2,)
    assert state["weight"].storage == data.StorageRef("0", "F32", 4, 2)


@pytest.mark.parametrize(
    "change",
    [
        "global",
        "offset",
        "stride",
        "shape",
        "grad",
        "hook",
        "duplicate",
        "trailer",
        "protocol",
        "memo",
        "construct",
        "large",
        "non_tensor",
        "storage_path",
    ],
)
def test_unknown_executable_or_ambiguous_state_is_rejected(change, tmp_path):
    values = {}
    if change == "global":
        values["global_name"] = "os\nsystem"
    if change == "offset":
        values["offset"] = 1
    if change == "stride":
        values["stride"] = (0,)
    if change == "shape":
        values["shape"] = (1,)
    if change == "grad":
        values["requires_grad"] = True
    if change == "hook":
        values["hooks"] = True
    if change == "duplicate":
        values["duplicate"] = True
    if change == "storage_path":
        values["storage"] = "../../secret"
    raw = metadata(**values)
    if change == "trailer":
        raw += b"cos\nsystem\n."
    if change == "protocol":
        raw = b"\x80\x04" + raw[2:]
    if change == "memo":
        raw = b"\x80\x02h\x01."
    if change == "construct":
        raw = b"\x80\x02cos\nsystem\n" + text("touch " + str(tmp_path / "executed")) + b"\x85R."
    if change == "large":
        raw = b"x" * (data.MAX_METADATA + 1)
    if change == "non_tensor":
        raw = b"\x80\x02}" + text("weight") + integer(1) + b"s."
    with pytest.raises(ValueError):
        data.parse(raw)
    assert not (tmp_path / "executed").exists()


def test_complete_layout_checks_do_not_read_any_tensor_payload():
    raw = checkpoint()
    first = archive.read_archive(io.BytesIO(raw))
    tensor = first["tensors"][0]

    class HeaderOnly(io.BytesIO):
        def read(self, count=-1):
            begin = self.tell()
            end = len(raw) if count < 0 else min(len(raw), begin + count)
            assert not (begin < tensor["data_offset"] + tensor["size_bytes"] and end > tensor["data_offset"])
            return super().read(count)

    result = archive.read_archive(HeaderOnly(raw))
    assert result["report"]["tensor_count"] == 1 and result["report"]["dtypes"] == ["F32"]
    assert result["report"]["storage_layout_verified"] and not result["report"]["runtime_qualified"]
    assert result["tensors"][0]["shape"] == [2]


@pytest.mark.parametrize(
    "change",
    ["compressed", "script", "path", "data_size", "missing", "local_name", "local_crc", "trailer", "count"],
)
def test_unsafe_or_inconsistent_archives_never_reach_tensor_loading(change):
    raw = checkpoint(
        compression=zipfile.ZIP_DEFLATED if change == "compressed" else zipfile.ZIP_STORED,
        extra_file="code/forward.py" if change == "script" else "../escape" if change == "path" else None,
        raw=metadata(storage="1") if change == "missing" else None,
    )
    if change in {"data_size", "local_name", "local_crc"}:
        with zipfile.ZipFile(io.BytesIO(raw)) as zip:
            info = zip.getinfo("weights/data/0")
        modified = bytearray(raw)
        if change == "data_size":
            modified[info.header_offset + 22 : info.header_offset + 26] = struct.pack("<I", 9)
        elif change == "local_crc":
            modified[info.header_offset + 14 : info.header_offset + 18] = b"\0" * 4
        else:
            modified[info.header_offset + 30] = ord("x")
        raw = bytes(modified)
    if change == "trailer":
        raw += b"untrusted"
    if change == "count":
        raw = raw[:-12] + b"\xff\xff\xff\xff" + raw[-8:]
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        archive.read_archive(io.BytesIO(raw))


def test_remote_metadata_can_defer_storage_spans_without_claiming_verified_layout():
    raw = checkpoint()
    native = archive.read_archive(io.BytesIO(raw))
    remote = archive.read_archive(io.BytesIO(raw), verify_local=False)
    assert native["report"]["header_sha256"] == remote["report"]["header_sha256"]
    assert not remote["report"]["storage_layout_verified"]
    assert remote["tensors"][0]["data_offset"] is None


def test_module_version_build_is_data_only_and_preserves_its_values():
    suffix = pickle.dumps({"_metadata": {"": {"version": 1}}}, protocol=2)[2:-1]
    state, versions = data.parse(metadata()[:-1] + suffix + b"b.")
    assert len(state) == 1 and versions == {"": {"version": 1}}
    for value in ({"__setstate__": "code"}, {"_metadata": {"": {"version": 1000}}}):
        with pytest.raises(ValueError):
            data.parse(metadata()[:-1] + pickle.dumps(value, protocol=2)[2:-1] + b"b.")


def test_shared_storage_and_excessive_stack_or_memo_are_rejected():
    aliased = metadata()[:-2] + metadata(key="other")[4:-2] + b"u."
    for raw in (
        aliased,
        b"\x80\x02}r" + struct.pack("<I", data.MAX_MEMO) + b".",
        b"\x80\x02}" + b")" * (data.MAX_STACK + 1) + b".",
    ):
        with pytest.raises(ValueError):
            data.parse(raw)


def test_every_truncated_metadata_prefix_fails_closed():
    raw = metadata()
    for length in range(len(raw)):
        with pytest.raises(ValueError):
            data.parse(raw[:length])


def test_large_streaming_record_keeps_its_exact_zip64_offset():
    base = 2**32 + 123
    name = "weights/data/0"
    extra = struct.pack("<HHQ", 1, 8, base)
    header = struct.pack("<4s5H3I2H", b"PK\x03\x04", 0, 8, 0, 0, 0, 0, 0, 0, len(name), len(extra))
    raw = header + name.encode() + extra

    class Sparse(io.BytesIO):
        def seek(self, offset, whence=0):
            assert whence == 0
            return super().seek(offset - base)

    info = zipfile.ZipInfo(name)
    info.header_offset = base
    info.flag_bits = 8
    info.file_size = 1280
    info.CRC = 1234
    assert archive._local(Sparse(raw), info, base + len(raw) + 1280) == base + len(raw)
    with pytest.raises(ValueError):
        archive._local(Sparse(raw[:-8] + struct.pack("<Q", base + 1)), info, base + len(raw) + 1280)


@pytest.fixture
def owned(tmp_path):
    import hashlib

    raw = checkpoint()
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "models/store" / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    path.chmod(0o400)
    report = archive.inspect_archive(path, len(raw), path.stat().st_mtime)
    return path, {
        "sha256": digest,
        "size_bytes": len(raw),
        "mtime": path.stat().st_mtime,
        "schema_sha256": report["schema_sha256"],
        "module_metadata_sha256": report["module_metadata_sha256"],
    }


def test_mapped_tensors_outlive_the_file_handle_and_cannot_modify_the_original(owned, monkeypatch):
    import sys
    from types import SimpleNamespace

    from ai_station_runner.torch_state_loader import load_weights

    path, expected = owned
    original = path.read_bytes()

    class Tensor:
        def __init__(self, mapping, *, dtype, count, offset):
            self.mapping, self.offset, self.count = mapping, offset, count
            assert dtype == "F32"

        def reshape(self, shape):
            assert shape == (2,)
            return self

        def values(self):
            return struct.unpack_from("<ff", self.mapping, self.offset)

    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(frombuffer=Tensor, float32="F32", float16="F16")
    )
    weights = load_weights(path, **expected)
    assert weights["weight"].values() == (1.25, -2.5) and weights._metadata == {}
    tensor = weights["weight"]
    tensor.mapping[tensor.offset : tensor.offset + 4] = struct.pack("<f", 10)
    assert tensor.values() == (10, -2.5) and path.read_bytes() == original


@pytest.mark.parametrize("change", ["hash", "graph", "versions", "mtime", "writable", "symlink"])
def test_invalid_owned_weights_are_rejected_before_importing_torch(owned, monkeypatch, change):
    import sys

    from ai_station_runner.torch_state_loader import load_weights

    path, expected = owned
    monkeypatch.setitem(sys.modules, "torch", None)
    if change == "hash":
        wrong = path.with_name("f" * 64)
        path.rename(wrong)
        path = wrong
        expected["sha256"] = "f" * 64
    elif change == "graph":
        expected["schema_sha256"] = "f" * 64
    elif change == "versions":
        expected["module_metadata_sha256"] = "f" * 64
    elif change == "mtime":
        expected["mtime"] = 0
    elif change == "writable":
        path.chmod(0o600)
    else:
        saved = path.with_suffix(".original")
        path.rename(saved)
        path.symlink_to(saved)
    with pytest.raises(ValueError):
        load_weights(path, **expected)
