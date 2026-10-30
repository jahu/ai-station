# Persistent creative workspaces

Images, Video, Music, Speech and Avatars retain private workspaces rather than
discarding the current form when navigating away. Select an existing workspace
from **Your workspaces**, or use **New** to start another idea. The workspace URL
can be bookmarked. Existing Run/MediaJob links retain their previous behavior.

The draft saves automatically. Each generation adds a version containing its
prompt, exact settings, execution status and published results. Refreshing or
returning from Library restores the history and draft. **Use these settings**
starts a linked variation; **Edit this image** selects that exact output as the
new input. Earlier versions remain available. Narration and lyrics are restored
verbatim. Workspace names can be edited, and archiving retains history; restore
an archived workspace to continue it.

Prompt translation receipts and review controls remain available in the version
history, including editing the prepared prompt before generation. Resource waits
retain their existing explanation. A translation recovery that starts a separate
attempt opens that attempt's Run inspector; the original history is retained.

## Execution and ownership

Migration 0039 introduces an owner-scoped `CreativeSession` and append-only
`CreativeTurn`. A turn groups an existing Task and its ordinary Runs; it is not
an executor or a second job engine. The generation endpoint dispatches only to
the existing typed image, video, music, speech or avatar request builders.
Video scenes/full films and full-recording Sonic/Echo avatars use the existing
MediaJob publisher and composition pipeline. Preparation success alone does not
mean the whole version succeeded. Stop cancels the complete owned Task through
the existing cancellation service; workers retain native process ownership.

One transaction creates the Task/Run graph, immutable turn and submission
receipt. A repeated identical receipt returns the same turn. A changed payload
or a cross-session collision is rejected. Parent versions and source artifacts
must belong to the current user's permitted scope. Administrators inspect
creative history through the existing explicit, read-only account inspector.

Draft and metadata writes are serialized, versioned and limited to 64 KiB.
Account-scoped browser recovery supplements server persistence; account switches
invalidate pending saves. Conflicts show a recovery action instead of silently
overwriting another device's changes. After submission the UI fetches fresh
server state even when the application's normal query cache is still fresh.

## Qualification and rollout

API tests cover all five capabilities, restart persistence, paging, concurrent
receipts, ownership, rollback, source lineage and cancellation. Full-film and
whole-recording fake-native workflows verify complete Task outcomes and final
artifacts. Component tests exercise all five actual forms and exact script/lyrics
restoration. Compiled desktop/mobile browser checks use a real private API,
separate synthetic image worker and temporary database, including generation,
selected-output editing, navigation/reload and another user's denial.

These checks do not perform real model inference or requalify image/video quality.
Private evidence is under `data/acceptance/creative-workspaces-20261030/`.
PRs #514/#515 are deployed on the development workstation after a preserved-data
0038 → 0039 migration and compiled production desktop/mobile checks. The native
Runner and loaded models were not restarted. General progress and ETA improvements
remain NR-02 in the [release plan](plans/next-release-0.1.md).
