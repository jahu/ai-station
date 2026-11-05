"""Bounded metadata-only reuse estimates over previously verified owned objects.

This is advice, never hash/runtime authority. The normal downloader rehashes all
reused bytes and native verification rechecks the complete binding before use.
"""

import math
import os
import stat

from sqlalchemy import select

from app.config import get_settings
from app.hub_sources import SHA256
from app.models import ModelDefinition, ModelFile


def components(report, file):
    group_id = file.get("bundle_id")
    if group_id:
        group = next((g for g in report.get("model_bundles", []) if g.get("id") == group_id), None)
        if not group or group.get("status") != "complete_metadata":
            return []
        parts = group.get("parts", [])
        if (
            not 2 <= len(parts) <= 64
            or len({p.get("sha256") for p in parts}) != len(parts)
            or any(not isinstance(p.get("sha256"), str) or not SHA256.fullmatch(p["sha256"]) for p in parts)
        ):
            return []
        return parts
    return [file] if file.get("identity_available") is True else []


def observations(session, wanted):
    from app.gguf_bindings import OwnedBundle, checked_proof

    result = {}
    # The public-source budget bounds this lookup; never crawl the whole store.
    if len(wanted) > 4096:
        return result
    for start in range(0, len(wanted), 400):
        models = list(
            session.scalars(
                select(ModelFile).where(
                    ModelFile.sha256.in_(sorted(wanted)[start : start + 400]),
                    ModelFile.availability == "present",
                )
            )
        )
        primary = {
            m.id: m for m in models if m.relative_path == "models/store/" + m.sha256 and m.host_path is None
        }
        for model in primary.values():
            result[model.sha256] = {"size_bytes": model.size_bytes, "mtime": model.mtime}
        if not primary:
            continue
        for definition in session.scalars(
            select(ModelDefinition).where(ModelDefinition.file_id.in_(primary))
        ):
            raw = (definition.metadata_json or {}).get("model_bundle")
            if raw is None:
                continue
            try:
                bundle = OwnedBundle.model_validate(raw)
                checked_proof(bundle, definition.metadata_json.get("bundle_proof"))
                model = primary[definition.file_id]
                first = bundle.parts[0]
                if (model.sha256, model.size_bytes, model.mtime) != (
                    first.sha256,
                    first.size_bytes,
                    first.mtime,
                ):
                    continue
                for part in bundle.parts:
                    if part.sha256 in wanted:
                        result[part.sha256] = {"size_bytes": part.size_bytes, "mtime": part.mtime}
            except ValueError:
                continue
    return result


def reusable(session, report, check):
    wanted = {
        p.get("sha256")
        for file in report.get("files", [])
        for p in components(report, file)
        if isinstance(p.get("sha256"), str) and SHA256.fullmatch(p["sha256"])
    }
    known = observations(session, wanted)
    if not known:
        return {}
    descriptors = []
    result = {}
    try:
        root = get_settings().data_dir.resolve(strict=True)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for name in ("models", "store"):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        for index, (digest, observation) in enumerate(known.items()):
            if index % 16 == 0:
                check()
            size, modified = observation["size_bytes"], observation["mtime"]
            if (
                type(size) is not int
                or not 0 < size <= 256 * 1024**3
                or type(modified) not in {int, float}
                or not math.isfinite(modified)
            ):
                continue
            try:
                info = os.stat(digest, dir_fd=fd, follow_symlinks=False)
            except OSError:
                continue
            if (
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and not info.st_mode & 0o222
                and info.st_size == size
                and info.st_mtime == modified
            ):
                result[digest] = size
    except OSError:
        return {}
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return result


def apply(session, report, check):
    """Annotate missing model bytes, retaining full runtime/companion allowances."""
    cached = reusable(session, report, check)
    for file in report.get("files", []):
        parts = components(report, file)
        disk = file["assessment"]["disk"]
        if not parts or any(type(p.get("size_bytes")) is not int or p["size_bytes"] <= 0 for p in parts):
            continue
        total = sum(p["size_bytes"] for p in parts)
        saved = sum(p["size_bytes"] for p in parts if cached.get(p.get("sha256")) == p["size_bytes"])
        budget = disk.get("install_bytes_upper_bound", disk.get("model_bundle_bytes", file.get("size_bytes")))
        if type(budget) is not int or budget < total:
            continue
        additional = budget - saved
        disk.update(
            reusable_model_bytes=saved,
            model_weights_available=saved == total,
            model_download_bytes_estimate=total - saved,
            additional_bytes_upper_bound=additional,
            reuse_verification="registry_and_read_only_storage_metadata; rehashed_before_install",
        )
        free, headroom = disk.get("free_bytes"), disk.get("headroom_bytes")
        if (
            type(free) in {int, float}
            and math.isfinite(free)
            and free >= 0
            and type(headroom) in {int, float}
            and math.isfinite(headroom)
            and headroom >= 0
        ):
            disk["status"] = "file_fits" if free >= additional + headroom else "insufficient"
        if saved:
            disk["note"] = (
                "Previously verified model objects are reused only after hash re-verification. Runtime, companions and staging retain their own space budget."
            )
    return set(cached)
