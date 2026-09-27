# Reviewed coding commits

Status: design for a subsequent increment; not an operational endpoint.

A user reviews a coding result and its validation, then explicitly requests a commit on its owned task branch. The control plane records an Approval containing the immutable review digest, source Run, validation outcome, project version and commit message. A separate ordinary Run performs the Git operation through the native Runner; HTTP handlers never run Git mutations.

The native operation revalidates its recorded source report, worktree owner, branch, HEAD and selected file hashes. It builds an isolated index from the expected parent and stages only reviewed blobs, bypassing content filters and hooks. It publishes with a compare-and-swap update of the exact owned `ai/` ref. Protected branches and unrelated working indexes are never targets. A journal is written before ref publication; uncertain interruption requires inspection rather than repeating a commit. The initial worktree base remains recorded, while a verified published head allows subsequent validation.

Commit completion produces an inspectable JSON artifact and `git.commit.created` event. Commit creation does not push, create a PR, merge or deploy. Those become separate approval-bound operations in the same workflow.
