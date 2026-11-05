"""Bounded publisher part sets; filename grouping never grants runtime admission."""

import hashlib
import json
import re

PART = re.compile(r"(.+)-([0-9]{5})-of-([0-9]{5})\.gguf\Z", re.I)
SUFFIX = re.compile(r"[0-9]{5}-of-[0-9]{5}\.gguf\Z", re.I)
MAX_PARTS = 64


def coordinate(filename):
    matched = PART.fullmatch(filename)
    return (matched[1], int(matched[2]), int(matched[3])) if matched else None


def looks_split(filename):
    return bool(SUFFIX.search(filename))


def annotate(files):
    groups, counts = {}, {}
    for file in files:
        value = coordinate(file["filename"])
        if value:
            prefix, index, count = value
            groups.setdefault((prefix, count), []).append((index, file))
            counts.setdefault(prefix, set()).add(count)
    bundles = []
    for (prefix, count), rows in groups.items():
        rows.sort(key=lambda row: row[0])
        indices = [index for index, _ in rows]
        bounded = 2 <= count <= MAX_PARTS and len(rows) <= MAX_PARTS
        complete = bounded and indices == list(range(1, count + 1))
        identities = all(
            file.get("identity_available") is True
            and type(file.get("size_bytes")) is int
            and 0 < file["size_bytes"] <= 256 * 1024**3
            and isinstance(file.get("sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", file["sha256"])
            for _, file in rows
        )
        unique = len({file.get("sha256") for _, file in rows}) == len(rows)
        status = (
            "unsupported_part_count"
            if not bounded
            else "conflicting_counts"
            if len(counts[prefix]) != 1
            else "invalid_parts"
            if len(set(indices)) != len(indices) or any(i < 1 or i > count for i in indices)
            else "missing_parts"
            if not complete
            else "unverified_identities"
            if not identities or not unique
            else "complete_metadata"
        )
        bundle = {
            "kind": "gguf_split",
            "name": prefix + ".gguf",
            "expected_parts": count,
            "observed_parts": len(rows),
            "status": status,
            "total_size_bytes": sum(file["size_bytes"] for _, file in rows)
            if status == "complete_metadata"
            else None,
            "parts": [
                {"index": index, **{key: file.get(key) for key in ("filename", "size_bytes", "sha256")}}
                for index, file in rows[:MAX_PARTS]
            ],
            "missing_parts": [i for i in range(1, count + 1) if i not in indices] if bounded else [],
            "native_verified": False,
            "installation_available": False,
        }
        identity = hashlib.sha256(
            json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        bundle["id"] = identity
        for _, file in rows:
            file["bundle_id"] = identity
        bundles.append(bundle)
    return bundles


def for_file(report, file):
    identity = file.get("bundle_id")
    return (
        next((b for b in report.get("model_bundles", []) if b.get("id") == identity), None)
        if identity
        else None
    )
