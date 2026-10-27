# Local proposal format correction

AGENT-006 preserved its workspace and history, but a local continuation failed
with `Invalid coding summary`; a validation correction also returned duplicate
or unselected paths. Keep those original failures and keep the parser strict.

The local adapter now checks the entire proposal before returning it to the
shared file-application executor. A schema or selected-file rejection permits
one fresh completion, using the identical task, guidance and source snapshot
plus the bounded validator reason. It does not accept the invalid proposal,
expand the allowed file list, run a tool, write an intermediate file or send the
rejected completion back as instructions. The common executor still rechecks
repository and file identities and enforces repair deletion restrictions.

At most two local proposal completions use the existing 8192-token per-response
limit, stream-size bounds, cancellation and overall native deadline. Truncated,
incomplete, transport and inference failures do not cause a replay. Both rejected
attempts emit inspectable `coding.proposal.rejected` log events. A second invalid
proposal fails the Run without applying files. A valid first response needs only
one completion. Validation/test repair keeps its separate existing budget.

Qualification includes fake streamed completions against disposable owned Git
worktrees: wrong summary type, duplicate paths, unselected paths, correction
success and repeated failure; every invalid candidate leaves files untouched.
Then perform an actual local-model website continuation in the browser, inspect
the changed heading, build download and unchanged workspace/history. This is a
repair plan and implementation contract, not a claim that browser QA is closed.
