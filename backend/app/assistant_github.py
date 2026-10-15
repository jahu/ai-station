"""Conversation-selected GitHub access; model plans cannot choose an account target."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.db import utcnow
from app.github_connector import repository_name
from app.models import Connector
from app.permissions import require
from app.runs import create_run


class GithubScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID
    expected_updated_at: AwareDatetime


def selected_connector(session, scope):
    row = session.get(Connector, str(scope.connector_id))
    if row is None or row.kind != "github" or not row.enabled:
        raise HTTPException(422, "Choose an enabled GitHub repository connector")
    if row.updated_at != scope.expected_updated_at:
        raise HTTPException(409, "GitHub connector changed; choose the repository again")
    repository_name(row.config_json.get("repository"))
    return row


def validate_scope(session, body):
    if not body.github:
        if body.action == "github.inspect":
            raise HTTPException(422, "Select a GitHub repository before sending")
        return
    if (
        body.action not in {"auto", "github.inspect"}
        or any(
            getattr(body, key, None)
            for key in (
                "image_artifact_ids",
                "audio_artifact_id",
                "attachments",
                "coding",
                "new_project",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
                "media",
                "speech_text",
                "upscale_result",
            )
        )
        or body.web_search.enabled
    ):
        raise HTTPException(422, "Read GitHub separately from media, research and coding actions")
    selected_connector(session, body.github)


def dispatch(session, parent):
    from app.connectors import active_check

    for permission in ("network_read", "github_read"):
        require(parent.effective_permissions, permission)
    scope = GithubScope.model_validate(parent.parameters["github"])
    row = selected_connector(session, scope)
    if active_check(session, row.id):
        raise HTTPException(
            409, "This repository already has an active refresh; inspect it before sending again"
        )
    run = create_run(
        session,
        parent.task,
        run_type="connector",
        capability="connector.github.read",
        executor_type="github_read",
        execution_target="host",
        parameters={
            "connector_id": row.id,
            "repository": row.config_json["repository"],
            "operation": "overview",
        },
        permissions=["network_read", "github_read"],
        retry_class="inspect",
        parent_run_id=parent.id,
    )
    row.status, row.last_run_id, row.updated_at = "checking", run.id, utcnow()
    return run
