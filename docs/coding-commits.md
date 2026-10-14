# Reviewed coding commits

[Selected source removals](coding-file-removal.md) enter the reviewed tree only
while the path remains absent and its recorded parent blob matches. Recreated or
redirected paths fail before ref advancement.

A successful coding proposal is review evidence, not permission to integrate it. The next Coding action explicitly queues a local `coding.commit` Run for the reviewed proposal. The Platform assistant shows the same review in the conversation and can queue that Run after an explicit acknowledgement, using the same domain service. It snapshots the proposal identity and commit message, requires successful configured validation, and never pushes or merges. A model-generated plan cannot grant Git write permission.

The Runner revalidates the owned worktree, task branch and proposal report. Only reviewed file contents with matching hashes and original executable bits may enter the commit. A private temporary index constructs a tree from the recorded parent and selected snapshots; unrelated worktree files are excluded. Git hooks, signing, filters and automatic maintenance are disabled. The task ref advances using Git's compare-and-swap parent check. The active checkout and protected branches are untouched.

Worktree manifests preserve the original base commit and track the new owned HEAD separately. Dispatch and commit publication are durable side effects: cancellation or a crash near ref advancement requires inspection, never blind retry. The result includes the commit ID, parent, branch and files as a JSON Artifact and structured `git.commit.created` event.

Validation uses disposable real Git repositories and fake coding providers: selected new/modified files commit successfully, unrelated files and the active checkout remain unchanged, hooks do not run, changed content/modes/index are refused, and request replays do not create another commit. The review UI shows one selected file patch at a time, cumulative totals against the task base when the proposal is a follow-up or repair, and download/Library actions for the stored `git_diff` artifact. The review acknowledgement reuses the shared list keyboard with a unique Review name; Space or Enter selects it and does not queue a commit. There is no inspectable review-ack Run. Component tests cover arrow-key file selection, review acknowledgement, cumulative labeling and artifact links. The earlier browser check of diff rendering, explicit acknowledgement and commit action is not re-claimed for this slice. Commits use the explicit local identity `AI Station <ai-station@localhost>`.
