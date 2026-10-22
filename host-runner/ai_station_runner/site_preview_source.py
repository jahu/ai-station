"""Bounded, immutable static-build broker. It never fetches a URL or extracts ZIPs."""

import hashlib
import io
import mimetypes
import os
import stat
import struct
import zipfile

from ai_station_runner.site_preview_protocol import MAX_RESPONSE, asset_path

MAX_ARCHIVE = 34 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024


class BuildSource:
    def __init__(self, path, sha256, size_bytes, entry="index.html"):
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size != size_bytes
                or not 0 < size_bytes <= MAX_ARCHIVE
            ):
                raise ValueError("Preview requires its frozen bounded build archive")
            data = handle.read(MAX_ARCHIVE + 1)
            after = os.fstat(handle.fileno())
            if (
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or len(data) != size_bytes
                or hashlib.sha256(data).hexdigest() != sha256
            ):
                raise ValueError("Preview archive changed after approval")
        # Bound directory parsing before ZipFile allocates one object per member.
        # Our build exporter writes ordinary single-disk ZIPs, not ZIP64/SFX archives.
        end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
        if end < 0 or end + 22 > len(data):
            raise ValueError("Preview build has no bounded ZIP directory")
        _, disk, central_disk, disk_count, count, directory_bytes, offset, comment = struct.unpack_from(
            "<4s4H2IH", data, end
        )
        if (
            disk
            or central_disk
            or disk_count != count
            or not 0 < count <= 1000
            or directory_bytes > 1024 * 1024
            or offset + directory_bytes > end
            or end + 22 + comment != len(data)
        ):
            raise ValueError("Preview ZIP directory exceeds its format or size budget")
        try:
            self.archive = zipfile.ZipFile(io.BytesIO(data))
            members = self.archive.infolist()
            if not 0 < len(members) <= 1000 or sum(item.file_size for item in members) > MAX_EXPANDED:
                raise ValueError("Preview archive exceeds its member or expansion budget")
            self.members = {}
            for item in members:
                name = asset_path(item.filename)
                if (
                    name in self.members
                    or item.is_dir()
                    or item.flag_bits & 1
                    or item.file_size > MAX_RESPONSE
                    or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG}
                ):
                    raise ValueError("Preview archive contains an unsafe member")
                self.members[name] = item
            self.entry = asset_path(entry)
            if self.entry not in self.members or not self.entry.lower().endswith(".html"):
                raise ValueError("Preview build has no selected HTML entry")
        except (zipfile.BadZipFile, NotImplementedError) as exc:
            raise ValueError("Preview build is not a supported ZIP archive") from exc

    def resource(self, path, *, document=False):
        path = asset_path(path)
        member = self.members.get(path)
        if member is None and document and "." not in path.rsplit("/", 1)[-1]:
            member = self.members[self.entry]
        if member is None:
            return 404, "text/plain", b"Build resource not found"
        try:
            with self.archive.open(member) as handle:
                body = handle.read(MAX_RESPONSE + 1)
                if len(body) != member.file_size or len(body) > MAX_RESPONSE:
                    raise ValueError("Preview resource exceeds its frozen size")
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            raise ValueError("Preview resource could not be verified") from exc
        content_type = {
            ".js": "text/javascript",
            ".mjs": "text/javascript",
            ".css": "text/css",
            ".html": "text/html",
        }.get("." + member.filename.rsplit(".", 1)[-1].lower())
        return (
            200,
            content_type or mimetypes.guess_type(member.filename)[0] or "application/octet-stream",
            body,
        )
