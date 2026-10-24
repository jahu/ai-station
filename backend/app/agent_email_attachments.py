"""Only reviewed final data exports may become agent email attachments."""

FILES = {
    "csv": ("result.csv", "document", "text/csv"),
    "xlsx": ("result.xlsx", "document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "png": ("chart.png", "image", "image/png"),
    "text": ("report.txt", "text", "text/plain"),
}
MAX_FILE_BYTES = 4 * 1024**2
MAX_TOTAL_BYTES = 16 * 1024**2


def required_outputs(definition):
    scope = definition.notification_policy.report_email
    kinds = scope.attachment_kinds if scope else []
    return [FILES[kind][0] for kind in kinds if kind != "csv"]


def describe(artifact, kind, source_id):
    name, artifact_type, mime = FILES[kind]
    if (
        artifact is None
        or artifact.run_id != source_id
        or artifact.trashed_at is not None
        or artifact.original_filename != name
        or artifact.artifact_type != artifact_type
        or artifact.mime_type != mime
        or artifact.metadata_json.get("agent_data_download" if kind == "csv" else "agent_data_export")
        is not True
        or not 1 <= artifact.size_bytes <= MAX_FILE_BYTES
    ):
        raise ValueError("A selected generated attachment is unavailable or exceeds its file limit")
    return {
        "kind": kind,
        "artifact_id": artifact.id,
        "filename": name,
        "mime_type": mime,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def snapshot(session, source, scope):
    from app.agent_email_results import artifact_content
    from app.models import Artifact

    if not scope.attachment_kinds:
        return []
    if source.executor_type != "agent_data_result" or source.status != "succeeded":
        raise ValueError("Email attachments require a successful verified data result")
    result = source.metadata_json.get("data_result") or {}
    exports = result.get("exports", [])
    if len({item["filename"] for item in exports}) != len(exports):
        raise ValueError("Generated attachment declarations are ambiguous")
    by_name = {item["filename"]: item["artifact_id"] for item in exports}
    by_name["result.csv"] = result.get("download_artifact_id")
    attachments = []
    for kind in scope.attachment_kinds:
        aid = by_name.get(FILES[kind][0])
        artifact = session.get(Artifact, aid) if aid else None
        item = describe(artifact, kind, source.id)
        artifact_content(artifact, binary=True)
        attachments.append(item)
    if (
        len({item["artifact_id"] for item in attachments}) != len(attachments)
        or sum(item["size_bytes"] for item in attachments) > MAX_TOTAL_BYTES
    ):
        raise ValueError("Generated email attachments exceed their combined limit")
    return attachments


def contents(session, manifest, source_id):
    from app.agent_email_results import artifact_content
    from app.models import Artifact

    if manifest is None:
        return []
    if not isinstance(manifest, list) or not 1 <= len(manifest) <= len(FILES):
        raise ValueError("The generated attachment manifest is invalid")
    values, seen, total = [], set(), 0
    for item in manifest:
        if not isinstance(item, dict) or item.get("kind") not in FILES:
            raise ValueError("The generated attachment format is invalid")
        artifact = session.get(Artifact, item.get("artifact_id"))
        if artifact is not None:
            session.refresh(artifact)
        if describe(artifact, item["kind"], source_id) != item or item["artifact_id"] in seen:
            raise ValueError("A generated attachment changed after review")
        seen.add(item["artifact_id"])
        total += item["size_bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Generated email attachments exceed their combined limit")
        values.append((item, artifact_content(artifact, binary=True)))
    return values
