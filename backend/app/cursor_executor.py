"""Cursor proposals, checked worktree edits and preserved review artifacts."""

from app.coding_proposal_executor import SelectedFileProposalExecutor


class CursorProposalExecutor(SelectedFileProposalExecutor):
    name = "cursor_proposal"
    error_type = "CursorExecutionFailed"
    permissions = ("filesystem_read", "workspace_write", "git_read", "external_ai")

    def start(self, runner, payload):
        return runner.start_cursor_proposal(payload)

    def report(self, runner, run_id):
        return runner.cursor_proposal_report(run_id)
