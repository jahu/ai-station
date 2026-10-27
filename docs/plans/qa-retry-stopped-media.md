# Explicit media retry after conversation Stop

Status: implementation on the feature branch; complete qualification and real browser retest pending.

UNIFIED-004 / QA-018 has recorded actual browser evidence in the acceptance report:
Stop cancels the owned image and translation review, but the visible Use original
action returns HTTP409 because it tries to publish into the stopped Task.

The durable Stop fence in `runs.create_run` and `task_control.cancel_task` is
correct and must remain. Do not clear it to make retry work. Existing retries
for an unstopped Task and `media_retry_projection.current_attempt` deliberately
require the same Task and parent chain; preserve their validation and history.

Implement an explicit fresh-intent path only after the existing native-process,
source-input and translation-receipt checks succeed. Serialize on the original
Task before choosing the path. If the original Task was stopped, create a new
Task with the exact authorized media request and effective permissions. Keep the
same owned conversation/project/agent references where applicable. Do not copy
old orchestration, media-plan or Stop metadata into it. Use a root media Run,
without a cross-Task parent pointer that could inherit old cancellation.

Bind source Run, source Task, fresh Task and fresh root Run through explicit
controller-owned retry provenance and the existing client request identity.
Identical replays return the original receipt; different duplicate requests
must not enqueue twice. Use a separate fresh-retry reference, rather than
putting a cross-Task pointer in the existing `retry_run_id` chain. Validate all
bindings before accepting a replay. Never weaken the ordinary chain's same-Task
checks. Preserve original/retranslated request values and frozen translator
policy using the existing preparation services.

For a chat-origin action, append a visible user action and an assistant result
bound to the new root Run in the same conversation. Its orchestration projection
can already render media Runs/artifacts for that new Task. The old turn remains
stopped. The new turn has independent Stop and readable source provenance.
Inspect `AssistantActions`, `components/media/PromptTranslation` and the chat
refresh handler: avoid a duplicate result on the old card, make its completed
retry explicit and keep historical prompt/translation evidence accessible.
Non-conversation Images/Runs entry points should still expose the fresh Task and
source Run. Do not require a new mode, hidden retry or manual user prompt.

Required tests: original/retranslation/reuse choices; unchanged unstopped retry;
idempotent replay and stale conflicting request; process completion pending;
missing/changed inputs and receipt rejection; transaction rollback; original
Stop retained and late enqueue refused; stale old Stop cannot cancel new media
or its translator/load/review; new Stop reaches only its own graph; same chat
shows a separate visible intent and renders its final artifact after reload.
Cover media retry siblings without accidentally relaxing long-film resume or
internal segment policies. Normal tests use fake executors and temporary data.

Then deploy the reviewed patch and perform the original browser Stop -> Use
original scenario against the real local pipeline, preserving both failed
history and the new result. Check Retry translation where available, as well as
new/old independent Stop behavior. Only then close QA-018 in the workbook.
