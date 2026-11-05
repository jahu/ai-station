"""Public publisher facts, never private download runs or raw recipe metadata."""

from urllib.parse import quote

from app.hub_sources import COMMIT, SHA256, parse_source


def publisher_source(definition, file):
    if file is None or not file.sha256:
        return None
    metadata = definition.metadata_json or {}
    source = metadata.get("source")
    if not isinstance(source, dict):
        # Older curated definitions can be identified without reading private
        # Runs. Never infer a publisher for an unknown/downloaded custom file.
        from app.setup_models import CANDIDATES

        source = next(
            (
                entry.model_dump(mode="json")
                for entry in CANDIDATES
                if entry.id == metadata.get("catalog_id")
                and entry.file.sha256 == file.sha256
                and entry.file.size_bytes == file.size_bytes
            ),
            None,
        )
    if not isinstance(source, dict):
        return None
    try:
        repository, revision, filename = (source[key] for key in ("repository", "revision", "filename"))
        physical = source["file"]
        if (
            not isinstance(repository, str)
            or parse_source(repository).repository != repository
            or not isinstance(revision, str)
            or not COMMIT.fullmatch(revision)
            or not isinstance(filename, str)
            or not 1 <= len(filename) <= 400
            or not isinstance(physical, dict)
            or not SHA256.fullmatch(str(physical.get("sha256", "")))
            or physical.get("sha256") != file.sha256
            or type(physical.get("size_bytes")) is not int
            or physical["size_bytes"] != file.size_bytes
        ):
            return None
        pinned = f"https://huggingface.co/{repository}/blob/{revision}/{quote(filename, safe='/')}"
        checked = parse_source(pinned)
        if (checked.repository, checked.revision, checked.filename) != (repository, revision, filename):
            return None
        license = source.get("license")
        if not isinstance(license, str) or not 1 <= len(license) <= 120 or any(ord(c) < 32 for c in license):
            license = "See publisher"
        return {
            "provider": "huggingface",
            "repository": repository,
            "revision": revision,
            "filename": filename,
            "sha256": file.sha256,
            "license": license,
            "pinned_url": pinned,
            "review_url": f"https://huggingface.co/{repository}/blob/main/{quote(filename, safe='/')}",
        }
    except (KeyError, ValueError, TypeError):
        return None
