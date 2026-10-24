"""Read verified final results as literal text or metadata-only summaries."""

import hashlib
import json
import os
import stat

from sqlalchemy import select

from app.agent_coding_policy import coding_provider
from app.agent_email_schema import MAX_BODY_CHARS, render_report
from app.artifacts import safe_join
from app.config import get_settings
from app.models import Artifact, Run

CODING_RESULTS = {"local_proposal", "codex_proposal", "cursor_proposal", "project_validation"}


def artifact_content(artifact, *, text=False, binary=False):
    limit = 512 * 1024 if text else 4 * 1024**2 if binary else 2 * 1024**3
    if artifact is None or artifact.trashed_at is not None or not 0 <= artifact.size_bytes <= limit:
        raise ValueError("The saved result is unavailable or exceeds its verification bound")
    path = safe_join(get_settings().data_dir, artifact.relative_path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != artifact.size_bytes:
            raise ValueError("The saved result is not its recorded regular file")
        digest, data, size = hashlib.sha256(), [], 0
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("The saved result grew beyond its verification bound")
            digest.update(chunk)
            if text or binary:
                data.append(chunk)
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or digest.hexdigest() != artifact.sha256:
            raise ValueError("The saved result changed before email preparation")
    return b"".join(data).decode("utf-8") if text else b"".join(data) if binary else None


def result_snapshot(session, source, root, definition, scope):
    if (
        source.status != "succeeded"
        or source.agent_id != root.agent_id
        or source.task_id != root.task_id
        or source.id == root.id
        or source.metadata_json.get("repair_run_id")
    ):
        raise ValueError("Only a completed result from this agent workflow can be delivered")
    artifacts = list(
        session.scalars(
            select(Artifact)
            .where(
                Artifact.run_id == source.id,
                Artifact.trashed_at.is_(None),
            )
            .order_by(Artifact.id)
        )
    )
    if any(item.metadata_json.get("partial") is True for item in artifacts):
        raise ValueError("Partial artifacts cannot be delivered as a completed result")
    family, report, report_artifact = None, None, None
    if definition.media:
        kind = definition.media.kind
        expected = {
            "image": "photo_pipe",
            "music": "ace_step_music",
            "speech": "chatterbox",
            "video": "media_compose",
            "avatar": "media_compose",
        }[kind]
        if source.executor_type != expected or source.metadata_json.get("upscale_run_id"):
            raise ValueError("Media preparation or an intermediate segment is not a final result")
        family = "media"
        types = {"image": "image", "music": "audio", "speech": "audio", "video": "video", "avatar": "video"}
        artifacts = [item for item in artifacts if item.artifact_type == types[kind]]
        if expected == "media_compose" and any(not item.metadata_json.get("verified") for item in artifacts):
            raise ValueError("The assembled media has not passed final verification")
    elif "python_data" in definition.tools:
        if source.executor_type != "agent_data_result":
            raise ValueError("Only the verified data result can be delivered")
        family = "data"
        result = source.metadata_json.get("data_result") or {}
        python = session.get(Run, source.parameters.get("python_run_id"))
        report_artifact = session.get(Artifact, result.get("report_artifact_id"))
        if (
            python is None
            or python.executor_type != "python"
            or python.status != "succeeded"
            or python.task_id != source.task_id
            or python.agent_id != source.agent_id
            or python.id != source.parent_run_id
            or report_artifact is None
            or report_artifact.artifact_type != "json"
            or report_artifact.mime_type != "application/json"
            or report_artifact.run_id != python.id
            or report_artifact.id not in python.metadata_json.get("output_artifact_ids", [])
        ):
            raise ValueError("The data report is not bound to its completed Python execution")
        from app.data_agents import DataAnswer

        answer = DataAnswer.model_validate_json(artifact_content(report_artifact, text=True))
        if any(result.get(key) != value for key, value in answer.model_dump().items()):
            raise ValueError("The saved data answer differs from its verified report")
        report = answer.answer
        if answer.columns:
            report += "\n\nTable preview (up to 20 rows):\n" + "\t".join(answer.columns)
            report += "\n" + "\n".join("\t".join(row) for row in answer.rows)
        artifacts.append(report_artifact)
    elif coding_provider(definition.tools):
        proposal_type = f"{coding_provider(definition.tools)}_proposal"
        if (
            source.executor_type not in {proposal_type, "project_validation"}
            or source.project_id != root.project_id
            or source.executor_type != "project_validation"
            and source.parameters.get("commands")
        ):
            raise ValueError("Coding preparation or an unchecked intermediate result cannot be delivered")
        family = "coding"
        validation = source.executor_type == "project_validation"
        filename = "validation.json" if validation else "coding-review.json"
        reports = [
            item
            for item in artifacts
            if item.original_filename == filename
            and item.artifact_type == "json"
            and item.mime_type == "application/json"
        ]
        if len(reports) != 1:
            raise ValueError("The coding result is missing its unique verified review report")
        review = json.loads(artifact_content(reports[0], text=True))
        if (
            review != source.metadata_json.get("validation" if validation else "coding_review")
            or review.get("run_id") != source.id
            or review.get("project_id") != source.project_id
            or review.get("worktree_run_id") != source.parameters.get("worktree_run_id")
            or validation
            and (
                any(item.get("exit_code") != 0 for item in review.get("commands", []))
                or [{"kind": item["kind"], "argv": item["argv"]} for item in review.get("commands", [])]
                != source.parameters.get("commands")
            )
        ):
            raise ValueError("The coding review differs from this completed result")
    elif source.executor_type == "agent_market" and source.parameters.get("tool") == "market.report":
        family = "report"
        reports = [
            item
            for item in artifacts
            if item.artifact_type == "markdown" and item.metadata_json.get("market")
        ]
        if len(reports) == 1:
            report_artifact = reports[0]
            report = artifact_content(report_artifact, text=True)
            artifacts = [report_artifact]
    elif source.executor_type == "agent" and source.parent_run_id == root.id:
        family = "report"
        reports = [
            item
            for item in artifacts
            if item.artifact_type == "markdown"
            and item.mime_type == "text/markdown"
            and item.metadata_json.get("partial") is False
            and item.metadata_json.get("agent_id") == source.agent_id
        ]
        if len(reports) == 1:
            report_artifact = reports[0]
            report = artifact_content(report_artifact, text=True)
            artifacts = [report_artifact]
    if (
        family is None
        or family == "report"
        and report_artifact is None
        or not artifacts
        or len(artifacts) > 20
    ):
        raise ValueError("The completed agent result has no supported verified output")
    references = []
    for item in artifacts:
        if item is not report_artifact:
            artifact_content(item)
        references.append(
            {
                "id": item.id,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "type": item.artifact_type,
                "mime_type": item.mime_type,
            }
        )
    references.sort(key=lambda value: value["id"])
    if scope.content == "report":
        if report is None or report_artifact is None:
            raise ValueError("Choose a result summary for coding or media output")
        rendered = render_report(scope, definition.name, source.id, report_artifact.id, report)
    else:
        # A summary never copies model text, code, data rows, filenames or inputs.
        name = " ".join(definition.name.replace("\x00", " ").split())[:200]
        body = f"AI Station agent result\nAgent: {name}\nRun: {source.id}\n\n"
        body += {
            "report": "Report ready.",
            "data": "Data processing result ready.",
            "coding": "Coding result ready for review.",
            "media": "Media generation complete.",
        }[family]
        body += "\n\nSaved outputs:\n" + "\n".join(f"- {item['type']}: {item['id']}" for item in references)
        if len(body) > MAX_BODY_CHARS:
            raise ValueError("The result summary exceeds its message bound")
        rendered = {"subject": (scope.subject_prefix + " · " + name)[:200], "body": body, "excerpted": False}
    from app.agent_email_attachments import snapshot as attachment_snapshot

    attachments = attachment_snapshot(session, source, scope)
    return {
        "family": family,
        "artifacts": references,
        "message": rendered,
        **({"attachments": attachments} if attachments else {}),
    }
