"""Local coding intent and native job transport; never grants external AI."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session

from app.coding_proposal_executor import CodingProposalExecutor
from app.coding_tasks import CodingTask, enqueue_coding_task
from app.db import session_scope
from app.providers import ProviderError
from app.runs import run_dict

router = APIRouter(prefix="/api/coding")


# Keep common input limits without accepting Cursor's external-AI permission.
class LocalCodingTask(CodingTask):
    model: str = Field(min_length=1, max_length=200)


@router.post("/local", status_code=202)
def create_local_task(body: LocalCodingTask, session: Annotated[Session, Depends(session_scope)]):
    try:
        run = enqueue_coding_task(session, body, provider="local")
    except ProviderError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return run_dict(run)


class LocalProposalExecutor(CodingProposalExecutor):
    name = "local_proposal"
    error_type = "LocalCodingFailed"
    permissions = ("filesystem_read", "workspace_write", "git_read", "network_read")

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "worktree_run_id": run.parameters["worktree_run_id"],
            "files": run.parameters["files"],
            "prompt": run.parameters["prompt"],
            "guidance": run.parameters["guidance"],
            "model": run.parameters["model"],
            "endpoint": run.parameters["endpoint"],
            "permissions": run.effective_permissions,
        }

    def start(self, runner, payload):
        return runner.start_local_proposal(payload)

    def report(self, runner, run_id):
        return runner.local_proposal_report(run_id)
