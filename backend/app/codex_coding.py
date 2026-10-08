"""Explicit external Codex proposals using the common coding workflow."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.coding_proposal_executor import SelectedFileProposalExecutor
from app.coding_tasks import CodingTask, enqueue_coding_task
from app.db import session_scope
from app.runs import run_dict

router = APIRouter(prefix="/api/coding", tags=["coding"])


class CodexTask(CodingTask):
    external_ai: Literal[True]


@router.post("/codex", status_code=202)
def create_codex_task(body: CodexTask, session: Annotated[Session, Depends(session_scope)]):
    run = enqueue_coding_task(session, body, provider="codex")
    session.commit()
    return run_dict(run)


class CodexProposalExecutor(SelectedFileProposalExecutor):
    permissions = ("filesystem_read", "workspace_write", "git_read", "external_ai")
    name = "codex_proposal"
    error_type = "CodexExecutionFailed"

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/codex-proposal", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/codex-proposal/{run_id}")
