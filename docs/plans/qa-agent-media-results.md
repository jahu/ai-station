# Agent media results in the conversation

Browser QA found that a linked media agent could publish a real image in Library
and its dedicated workspace while its conversation card showed only execution
history. Both the compact summary and expanded editor must show the existing
`AgentMediaResult`, including its inline preview, download and Library links.
Use the same latest-Task selection as the agent workspace: a newer pending or
failed execution must never display an older successful image as its result.

This is a presentation correction. It reuses published Runs and Artifacts; opening,
expanding or reloading the card must not enqueue generation or expose child retry
controls. Existing approvals, Stop, permissions and native execution are unchanged.
A fixed media-only definition does not require a text model; its execution label
must say so. Conversation guidance must refer to the single assistant rather than
the superseded Work mode.

Regression checks cover an actual image result component and Library link through
summary/editor transitions, read-only rendering, and newer pending execution
without fallback. Live browser retesting remains a separate gate after deployment;
retain the original QA failure in the private acceptance workbook.

## Save, then enable

The same browser campaign exposed an agent settings race: Save returned the new
revision, but Enable still read the previous detail-cache revision until a GET
finished, causing an avoidable conflict. Publish the acknowledged PUT response
into the shared detail cache before clearing the dirty state. Preserve history
when the update response omits Runs, then invalidate normally for fresh derived
state. Keep the server revision guard: genuine concurrent edits still conflict.
The regression holds the subsequent GET pending and verifies that Enable sends
exactly the revision acknowledged by Save.
