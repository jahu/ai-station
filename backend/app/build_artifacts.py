"""Adopt a checked native validation archive as an ordinary Artifact."""

import hashlib
import io
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from app.artifacts import register_file
from app.config import get_settings
from app.events import append_event
from app.models import Artifact

MAX_BYTES = 32 * 1024 * 1024


def register_build(session, run, report):
    exported = report.get("build_export")
    if exported is None:
        return
    if not isinstance(exported, dict):
        raise ValueError("Invalid build export report")
    if exported.get("status") == "unavailable":
        reason = exported.get("reason")
        if set(exported) != {"status", "reason"} or not isinstance(reason, str) or len(reason) > 1000:
            raise ValueError("Invalid build export warning")
        run.metadata_json = {**run.metadata_json, "build_export": exported}
        append_event(session, run.id, "build.export.unavailable", {"reason": reason})
        return
    expected = f"runtime/validation/{run.id}.build.zip"
    keys = {"status", "relative_path", "size_bytes", "sha256", "file_count", "uncompressed_bytes"}
    if (
        set(exported) != keys
        or exported["status"] != "ready"
        or exported["relative_path"] != expected
        or not report["commands"]
        or any(r["exit_code"] != 0 for r in report["commands"])
        or not any(r["kind"] == "build" for r in report["commands"])
        or any(type(exported[k]) is not int for k in ("size_bytes", "file_count", "uncompressed_bytes"))
        or not 0 < exported["file_count"] <= 1000
        or not 0 < exported["size_bytes"] <= MAX_BYTES + 2 * 1024 * 1024
        or not 0 <= exported["uncompressed_bytes"] <= MAX_BYTES
    ):
        raise ValueError("Build export does not match successful validation")
    path = get_settings().data_dir.resolve() / expected
    if path.resolve() != path:
        raise ValueError("Redirected build archive")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != exported["size_bytes"]:
            raise ValueError("Invalid build archive file")
        data = handle.read(MAX_BYTES + 2 * 1024 * 1024 + 1)
        after = os.fstat(handle.fileno())
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Build archive changed while reading")
    if hashlib.sha256(data).hexdigest() != exported["sha256"]:
        raise ValueError("Build archive hash changed")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if (
            len(members) != exported["file_count"]
            or sum(m.file_size for m in members) != exported["uncompressed_bytes"]
        ):
            raise ValueError("Build archive content does not match its report")
        seen = set()
        for member in members:
            name = member.filename
            parts = PurePosixPath(name).parts
            if (
                not parts
                or str(PurePosixPath(name)) != name
                or name.startswith("/")
                or "\\" in name
                or name in seen
                or member.is_dir()
                or any(p in {"", ".", ".."} or p.startswith(".") or ":" in p for p in parts)
                or any(ord(c) < 32 for c in name)
                or member.flag_bits & 1
                or stat.S_IFMT(member.external_attr >> 16) not in {0, stat.S_IFREG}
                or any(
                    word in name.lower()
                    for word in ("credential", "secret", "id_rsa", "id_ed25519", "node_modules")
                )
                or name.lower().endswith((".pem", ".key", ".p12", ".pfx"))
            ):
                raise ValueError("Unsafe build archive member")
            seen.add(name)
    artifact_id = str(uuid5(NAMESPACE_URL, f"ai-station:build:{run.id}"))
    existing = session.get(Artifact, artifact_id)
    if existing is not None:
        if existing.run_id != run.id or existing.sha256 != exported["sha256"]:
            raise ValueError("Build artifact identity changed")
        artifact = existing
    else:
        # Register the verified bytes, not a path a caller could change after hashing.
        with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
            handle.write(data)
            handle.flush()
            artifact = register_file(
                session,
                source=Path(handle.name),
                artifact_id=artifact_id,
                artifact_type="archive",
                mime_type="application/zip",
                original_filename="project-build.zip",
                run_id=run.id,
                metadata={
                    "role": "coding_build",
                    "project_id": run.project_id,
                    "validation_run_id": run.id,
                    "source_run_id": run.parent_run_id,
                    "worktree_run_id": run.parameters["worktree_run_id"],
                    "file_count": exported["file_count"],
                    "uncompressed_bytes": exported["uncompressed_bytes"],
                },
            )
    run.metadata_json = {**run.metadata_json, "build_artifact_id": artifact.id, "build_export": exported}
