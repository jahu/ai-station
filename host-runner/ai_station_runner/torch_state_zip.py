"""Bounded uncompressed tensor archives, inspected without tensor payload reads.

Never extracts files or invokes a pickle/PyTorch loader. The closed metadata
decoder supplies only plain tensor descriptors; every local storage span is
checked before a native inference child may map its raw bytes.
"""

import hashlib
import json
import os
import re
import stat
import struct
import zipfile

from ai_station_runner.torch_state_data import MAX_METADATA, MAX_TENSORS, parse

MAX_FILE = 32 * 1024**3
MAX_DIRECTORY = 2 * 1024**2
MAX_ENTRIES = MAX_TENSORS + 6
_NAME = re.compile(
    r"([A-Za-z0-9_.-]{1,80})/(data\.pkl|byteorder|version|\.data/serialization_id|"
    r"\.format_version|\.storage_alignment|data/(?:0|[1-9][0-9]{0,5}))\Z"
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def directory_end(tail, size):
    """Validate the finite zero-comment ZIP/ZIP64 ending before ZIP allocates."""
    if not 128 <= size <= MAX_FILE or len(tail) != 128:
        raise ValueError("Tensor archive exceeds its size bound")
    end = struct.unpack("<4s4H2IH", tail[-22:])
    if end[0] != b"PK\x05\x06" or end[1:3] != (0, 0) or end[3] != end[4] or end[7] != 0:
        raise ValueError("Use one complete tensor ZIP without comments or multiple disks")
    count, length, offset, boundary = end[4], end[5], end[6], size - 22
    if tail[-42:-38] == b"PK\x06\x07":
        locator = struct.unpack("<4sIQI", tail[-42:-22])
        record = struct.unpack("<4sQ2H2I4Q", tail[-98:-42])
        if (
            locator[1] != 0
            or locator[2] != size - 98
            or locator[3] != 1
            or record[0] != b"PK\x06\x06"
            or record[1] != 44
            or record[4:6] != (0, 0)
            or record[6] != record[7]
            or count not in {0xFFFF, record[7]}
            or length not in {0xFFFFFFFF, record[8]}
            or offset not in {0xFFFFFFFF, record[9]}
        ):
            raise ValueError("Unsupported or inconsistent tensor ZIP64 directory")
        count, length, offset, boundary = record[7], record[8], record[9], size - 98
    if (
        not 4 <= count <= MAX_ENTRIES
        or not 46 * count <= length <= MAX_DIRECTORY
        or offset < 30
        or offset + length != boundary
    ):
        raise ValueError("Tensor archive directory exceeds its bound")
    return offset, length, count


def _read(handle, offset, length, size):
    if not 0 <= offset <= size or not 0 <= length <= MAX_METADATA or offset + length > size:
        raise ValueError("Tensor metadata read exceeds its bound")
    handle.seek(offset)
    value = handle.read(length)
    if len(value) != length:
        raise ValueError("Truncated tensor archive metadata")
    return value


def _local(handle, info, size):
    header = struct.unpack("<4s5H3I2H", _read(handle, info.header_offset, 30, size))
    if (
        header[0] != b"PK\x03\x04"
        or header[2] != info.flag_bits
        or header[3] != 0
        or header[9] != len(info.filename.encode("ascii"))
        or header[10] > 4096
    ):
        raise ValueError("Tensor archive local record changed")
    name = _read(handle, info.header_offset + 30, header[9], size)
    if name != info.filename.encode("ascii"):
        raise ValueError("Tensor archive directory and local names disagree")
    extra = _read(handle, info.header_offset + 30 + header[9], header[10], size)
    cursor, zip64 = 0, None
    while cursor < len(extra):
        if cursor + 4 > len(extra):
            raise ValueError("Truncated tensor archive extra record")
        tag, length = struct.unpack("<HH", extra[cursor : cursor + 4])
        cursor += 4
        if cursor + length > len(extra):
            raise ValueError("Tensor archive extra record exceeds its bound")
        if tag == 1:
            if zip64 is not None or length not in {8, 16}:
                raise ValueError("Ambiguous local tensor ZIP64 size")
            zip64 = struct.unpack("<" + "Q" * (length // 8), extra[cursor : cursor + length])
        cursor += length
    if info.flag_bits & 8:
        if (
            header[6] not in {0, info.CRC}
            or any(n not in {0, 0xFFFFFFFF, info.file_size} for n in header[7:9])
            or zip64 is not None
            and zip64 != (info.header_offset,)
            and any(n not in {0, info.file_size} for n in zip64)
        ):
            raise ValueError("Invalid streaming tensor record sizes")
    else:
        sizes = header[7:9]
        if any(n == 0xFFFFFFFF for n in sizes):
            if zip64 is None or any(n != info.file_size for n in zip64):
                raise ValueError("Invalid local tensor ZIP64 size")
        elif sizes != (info.file_size, info.file_size):
            raise ValueError("Local tensor record sizes disagree")
        if header[6] != info.CRC:
            raise ValueError("Local tensor record checksum disagrees")
    return info.header_offset + 30 + header[9] + header[10]


def _inventory(archive, offset, count):
    items = archive.infolist()
    if len(items) != count or archive.start_dir != offset or items[0].header_offset != 0:
        raise ValueError("Unexpected tensor archive inventory")
    names, prefix = {}, None
    for info in items:
        match = _NAME.fullmatch(info.filename)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if (
            match is None
            or match[1] in {".", ".."}
            or info.filename in names
            or prefix is not None
            and match[1] != prefix
            or mode not in {0, stat.S_IFREG}
            or info.flag_bits & ~0x808
            or info.compress_type != zipfile.ZIP_STORED
            or info.compress_size != info.file_size
            or info.header_offset < 0
            or info.header_offset + 30 + len(info.filename) + info.file_size > offset
        ):
            raise ValueError("Only bounded, direct, uncompressed tensor files are supported")
        prefix = match[1]
        names[info.filename] = info
    base = prefix + "/"
    if any(base + name not in names for name in ("data.pkl", "byteorder", "version")):
        raise ValueError("Missing tensor archive metadata")
    ordered = sorted(items, key=lambda info: info.header_offset)
    for index, info in enumerate(ordered):
        following = ordered[index + 1].header_offset if index + 1 < len(ordered) else offset
        if info.header_offset + 30 + len(info.filename) + info.file_size > following:
            raise ValueError("Overlapping tensor archive entries")
    return names, base, ordered


def _metadata_size(relative, info):
    if not 0 < info.file_size <= (MAX_METADATA if relative == "data.pkl" else 64):
        raise ValueError("Tensor archive metadata exceeds its bound")


def metadata_ranges(handle):
    """Return metadata-only local extents after bounded directory validation.

    A remote caller may provide only tail/directory bytes initially. Each
    returned interval ends before the next entry's header, so no tensor entry
    (header or raw storage) needs to be fetched. All local metadata bytes are
    then decoded by the same read_archive implementation.
    """
    handle.seek(0, 2)
    size = handle.tell()
    offset, length, count = directory_end(_read(handle, size - 128, 128, size), size)
    _read(handle, offset, length, size)
    result = []
    with zipfile.ZipFile(handle) as archive:
        _, base, ordered = _inventory(archive, offset, count)
        for index, info in enumerate(ordered):
            relative = info.filename[len(base) :]
            if relative.startswith("data/"):
                continue
            _metadata_size(relative, info)
            following = ordered[index + 1].header_offset if index + 1 < len(ordered) else offset
            # Local names/extras and a streaming descriptor have finite bounds.
            # No arbitrary gap can become an ostensibly harmless metadata read.
            maximum = 30 + len(info.filename) + 4096 + info.file_size + 24
            if following - info.header_offset > maximum:
                raise ValueError("Tensor metadata local extent exceeds its bound")
            result.append((info.header_offset, following - 1))
    return result


def read_archive(handle, *, verify_local=True):
    """Inspect a seekable metadata view; remote views may defer local payload spans."""
    handle.seek(0, 2)
    size = handle.tell()
    tail = _read(handle, size - 128, 128, size)
    offset, length, count = directory_end(tail, size)
    central = _read(handle, offset, length, size)
    with zipfile.ZipFile(handle) as archive:
        names, base, ordered = _inventory(archive, offset, count)
        metadata = {}
        for name, info in names.items():
            relative = name[len(base) :]
            if relative.startswith("data/"):
                continue
            _metadata_size(relative, info)
            metadata[relative] = archive.read(info)
        if metadata["byteorder"] != b"little" or metadata["version"] != b"3\n":
            raise ValueError("Use the supported little-endian tensor ZIP version")
        for name, expected in ((".format_version", b"1"), (".storage_alignment", b"64")):
            if name in metadata and metadata[name].strip() != expected:
                raise ValueError("Unsupported tensor archive storage format")
        if ".data/serialization_id" in metadata and not re.fullmatch(
            rb"[0-9]{1,64}", metadata[".data/serialization_id"]
        ):
            raise ValueError("Invalid tensor serialization identity")
        state, versions = parse(metadata["data.pkl"])
        expected = {base + "data/" + tensor.storage.key for tensor in state.values()}
        if expected != {name for name in names if name[len(base) :].startswith("data/")}:
            raise ValueError("Tensor storages and archive files disagree")
        data_offsets = {}
        if verify_local:
            for index, info in enumerate(ordered):
                begin = _local(handle, info, size)
                end = begin + info.file_size
                following = ordered[index + 1].header_offset if index + 1 < len(ordered) else offset
                gap = following - end
                if info.flag_bits & 8:
                    if gap not in {16, 24}:
                        raise ValueError("Invalid streaming tensor record extent")
                    descriptor = _read(handle, end, gap, size)
                    values = struct.unpack("<4sI" + ("II" if gap == 16 else "QQ"), descriptor)
                    if values != (b"PK\x07\x08", info.CRC, info.file_size, info.file_size):
                        raise ValueError("Streaming tensor descriptor disagrees")
                elif gap != 0:
                    raise ValueError("Overlapping or hidden tensor archive extents")
                data_offsets[info.filename] = begin
        tensors = []
        for name, tensor in state.items():
            info = names[base + "data/" + tensor.storage.key]
            if info.file_size != tensor.storage.elements * tensor.storage.width:
                raise ValueError("Tensor shape and raw storage extent disagree")
            begin = data_offsets.get(info.filename)
            if begin is not None and begin % 64:
                raise ValueError("Tensor storage alignment differs from the supported format")
            tensors.append(
                {
                    "name": name,
                    "dtype": tensor.storage.dtype,
                    "shape": list(tensor.shape),
                    "data_offset": begin,
                    "size_bytes": info.file_size,
                }
            )
    report = {
        "source": "pytorch_zip_tensor_data",
        "tensor_count": len(tensors),
        "schema_sha256": fingerprint({v["name"]: v["shape"] for v in tensors}),
        "module_metadata_sha256": fingerprint(versions),
        "dtypes": sorted({v["dtype"] for v in tensors}),
        "tensor_storage_bytes": sum(v["size_bytes"] for v in tensors),
        "header_sha256": fingerprint(
            {
                "directory": hashlib.sha256(central).hexdigest(),
                "metadata": {k: hashlib.sha256(v).hexdigest() for k, v in metadata.items()},
            }
        ),
        "header_bytes": 128 + length + sum(len(v) for v in metadata.values()),
        "storage_layout_verified": verify_local,
        "runtime_qualified": False,
    }
    return {"report": report, "tensors": tensors, "module_versions": versions}


def inspect_archive(path, size_bytes, mtime):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size != size_bytes
            or abs(before.st_mtime - mtime) > 0.001
        ):
            raise ValueError("Tensor archive changed since its observation")
        try:
            report = read_archive(handle)["report"]
        except (zipfile.BadZipFile, NotImplementedError, UnicodeError, struct.error) as exc:
            raise ValueError("Invalid closed tensor archive") from exc
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Tensor archive changed during inspection")
        return report
