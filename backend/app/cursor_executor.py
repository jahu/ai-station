"""Cursor proposals, checked worktree edits and preserved review artifacts."""

from app.coding_proposal_executor import CodingProposalExecutor


class CursorProposalExecutor(CodingProposalExecutor):
    name = "cursor_proposal"
    error_type = "CursorExecutionFailed"
    permissions = ("filesystem_read", "workspace_write", "git_read", "external_ai")

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "worktree_run_id": run.parameters["worktree_run_id"],
            "files": run.parameters["files"],
            "prompt": run.parameters["prompt"],
            "guidance": run.parameters["guidance"],
            "model": run.parameters["model"],
            "permissions": run.effective_permissions,
        }

    def start(self, runner, payload):
        return runner.start_cursor_proposal(payload)

    def report(self, runner, run_id):
        return runner.cursor_proposal_report(run_id)
