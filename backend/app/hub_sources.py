"""Bounded public model metadata. Publisher input never becomes executable code."""

import json
import re
from typing import Literal
from urllib.parse import quote, unquote, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict

from app.hub_model_parts import annotate as annotate_parts
from app.hub_model_parts import coordinate as part_coordinate
from app.model_download_files import _wait, response

PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
MAX_BYTES = 2 * 1024 * 1024


class HubSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["huggingface"] = "huggingface"
    repository: str
    revision: str = "main"
    filename: str | None = None


def parse_source(value: str) -> HubSource:
    if not isinstance(value, str) or not 3 <= len(value) <= 1800:
        raise ValueError("Paste a Hugging Face model repository or file link")
    if re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise ValueError("Model links cannot contain whitespace or control characters")
    if "://" not in value:
        parts = value.split("/")
        if len(parts) == 2 and all(PART.fullmatch(p) for p in parts):
            return HubSource(repository=value)
        raise ValueError("Use publisher/model or a Hugging Face HTTPS link")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "huggingface.co"
        or parsed.fragment
        or parsed.query not in {"", "download=true"}
        or re.search(r"%2f|%5c|%25", parsed.path, re.I)
    ):
        raise ValueError("Use a public huggingface.co HTTPS model link without credentials")
    try:
        path = unquote(parsed.path, errors="strict")
    except UnicodeError as exc:
        raise ValueError("Invalid model link encoding") from exc
    parts = path.strip("/").split("/")
    if any(p in {"", ".", ".."} or re.search(r"[\\\x00-\x1f\x7f]", p) for p in parts):
        raise ValueError("Invalid model path")
    if len(parts) < 2 or not all(PART.fullmatch(p) for p in parts[:2]):
        raise ValueError("Use a model repository, not a collection or search page")
    repository = "/".join(parts[:2])
    if len(parts) == 2:
        return HubSource(repository=repository)
    if len(parts) < 4 or parts[2] not in {"tree", "blob", "resolve"} or not REVISION.fullmatch(parts[3]):
        raise ValueError("Use a repository, tree, blob or resolve model link")
    if parts[2] != "tree" and len(parts) < 5:
        raise ValueError("A file link needs a filename")
    if parts[2] == "tree" and len(parts) != 4:
        raise ValueError("Choose a whole repository or a specific file")
    return HubSource(repository=repository, revision=parts[3], filename="/".join(parts[4:]) or None)


async def metadata_json(url, check):
    # All callers construct fixed HF API/immutable config URLs after validation.
    # Reuse the download transport's per-hop public DNS pinning and TLS checks.
    async with response(url, 0, check) as result:
        if result.status_code in {401, 403}:
            raise ValueError("This model requires publisher access; no credentials were sent")
        if result.status_code == 404:
            raise ValueError("Model or revision was not found on Hugging Face")
        if result.status_code == 429:
            raise ValueError("Hugging Face request limit reached; try again later")
        result.raise_for_status()
        if result.status_code != 200 or result.headers.get("content-encoding", "identity") != "identity":
            raise ValueError("Model metadata must be an uncompressed JSON response")
        length = result.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
            raise ValueError("Model metadata exceeds its size limit")
        data = bytearray()
        chunks = result.aiter_raw(chunk_size=65536).__aiter__()
        while True:
            try:
                chunk = await _wait(check, anext(chunks), 35)
            except StopAsyncIteration:
                break
            if len(data) + len(chunk) > MAX_BYTES:
                raise ValueError("Model metadata exceeds its size limit")
            data.extend(chunk)
        check()
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ValueError("Model metadata is not valid bounded JSON") from exc


async def inspect_source(source: HubSource, check):
    # Re-parse even persisted input; no code relies on model_construct/model_copy.
    source = parse_source(
        f"https://huggingface.co/{source.repository}/tree/{source.revision}"
        if source.filename is None
        else f"https://huggingface.co/{source.repository}/blob/{source.revision}/{quote(source.filename, safe='/')}"
    )
    raw = await metadata_json(
        f"https://huggingface.co/api/models/{source.repository}/revision/{source.revision}?blobs=true", check
    )
    if (
        not isinstance(raw, dict)
        or raw.get("id") != source.repository
        or not isinstance(raw.get("sha"), str)
        or not COMMIT.fullmatch(raw["sha"])
        or not isinstance(raw.get("siblings"), list)
        or len(raw["siblings"]) > 4096
        or raw.get("private") is True
    ):
        raise ValueError("Publisher did not return a matching public immutable model revision")
    files, seen = [], set()
    selected_part = part_coordinate(source.filename) if source.filename else None
    for row in raw["siblings"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid publisher file metadata")
        filename = row.get("rfilename")
        if not isinstance(filename, str) or len(filename) > 1000:
            raise ValueError("Invalid publisher filename")
        checked = parse_source(
            f"https://huggingface.co/{source.repository}/blob/{raw['sha']}/{quote(filename, safe='/')}"
        )
        if checked.filename != filename or filename in seen:
            raise ValueError("Ambiguous publisher file metadata")
        seen.add(filename)
        if source.filename and filename != source.filename:
            other_part = part_coordinate(filename)
            if selected_part is None or other_part is None or other_part[0] != selected_part[0]:
                continue
        lower = filename.lower()
        if not lower.endswith((".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx")):
            continue
        lfs = row.get("lfs") or {}
        if not isinstance(lfs, dict):
            raise ValueError("Invalid publisher object metadata")
        size, sha = lfs.get("size", row.get("size")), lfs.get("sha256")
        verified_identity = bool(
            type(size) is int
            and 0 < size <= 256 * 1024**3
            and isinstance(sha, str)
            and SHA256.fullmatch(sha)
            and ("size" not in row or row["size"] == size)
        )
        files.append(
            {
                "filename": filename,
                "size_bytes": size if type(size) is int and 0 < size <= 256 * 1024**3 else None,
                "sha256": sha if verified_identity else None,
                "identity_available": verified_identity,
                "format": lower.rsplit(".", 1)[-1],
                "source_url": f"https://huggingface.co/{source.repository}/resolve/{raw['sha']}/{quote(filename, safe='/')}",
                "unsafe_serialization": lower.endswith((".bin", ".pt", ".pth")),
            }
        )
    if source.filename and source.filename not in seen:
        raise ValueError("The selected file is absent from this immutable revision")
    bundles = annotate_parts(files)
    if source.filename:
        files = [file for file in files if file["filename"] == source.filename]
        selected_bundles = {file.get("bundle_id") for file in files}
        bundles = [bundle for bundle in bundles if bundle["id"] in selected_bundles]
    card = raw.get("cardData") if isinstance(raw.get("cardData"), dict) else {}
    license_name = card.get("license")
    bases = card.get("base_model", [])
    bases = [bases] if isinstance(bases, str) else bases
    base_models = []
    if isinstance(bases, list) and len(bases) <= 4:
        for base in bases:
            try:
                parsed_base = parse_source(base)
                if parsed_base.filename is None and base == parsed_base.repository:
                    base_models.append(parsed_base.repository)
            except ValueError:
                continue
    gguf = raw.get("gguf") if isinstance(raw.get("gguf"), dict) else {}
    return {
        "provider": "huggingface",
        "repository": source.repository,
        "revision": raw["sha"],
        "source_url": f"https://huggingface.co/{source.repository}/tree/{raw['sha']}",
        "license": license_name[:120] if isinstance(license_name, str) else "Not declared",
        "license_url": f"https://huggingface.co/{source.repository}/blob/{raw['sha']}/README.md",
        "gated": raw.get("gated") is not None and raw.get("gated") is not False,
        "pipeline_hint": str(raw.get("pipeline_tag") or "")[:80],
        "architecture_hint": str(gguf.get("architecture") or "")[:80],
        "base_models": list(dict.fromkeys(base_models)),
        "files": files,
        **({"model_bundles": bundles} if bundles else {}),
        "metadata_only": True,
    }


def search_query(value):
    if (
        not isinstance(value, str)
        or not 2 <= len(value.strip()) <= 100
        or re.search(r"[\x00-\x1f\x7f]", value)
    ):
        raise ValueError("Search with 2–100 characters without control characters")
    return value.strip()


async def search_models(query, check):
    query = search_query(query)
    params = urlencode({"search": query, "sort": "downloads", "direction": -1, "limit": 12})
    raw = await metadata_json(f"https://huggingface.co/api/models?{params}", check)
    if not isinstance(raw, list) or len(raw) > 12:
        raise ValueError("Publisher search exceeded its result limit")
    items, seen = [], set()
    for row in raw:
        if not isinstance(row, dict) or row.get("private") is True:
            continue
        source = parse_source(row.get("id", ""))
        if source.repository in seen:
            continue
        seen.add(source.repository)
        downloads = row.get("downloads")
        items.append(
            {
                "repository": source.repository,
                "source_url": f"https://huggingface.co/{source.repository}",
                "pipeline_hint": str(row.get("pipeline_tag") or "")[:80],
                "downloads": downloads if type(downloads) is int and 0 <= downloads < 2**63 else None,
                "compatibility": "not_inspected",
            }
        )
    return {
        "kind": "search",
        "query": query,
        "items": items,
        "files": [],
        "metadata_only": True,
        "note": "Up to 12 publisher matches, ordered by downloads. Popularity is not compatibility or hardware fit.",
    }
