# Conversation continuity for transcripts

A follow-up such as “summarize that recording” or “translate
it” must receive the actual completed transcript already visible in the same
conversation. The existing local transcription executor, Chat completion and
assistant planner remain the only execution paths; no new execution engine or
permission is introduced.

Source selection is bound to the original assistant message, its succeeded
orchestration Run, one succeeded transcription child on the same Task and
conversation, and that child's primary TXT artifact. The artifact must remain
available, have the expected ownership/lineage, match its saved SHA-256 and equal
the verified report text. Failed, canceled, ambiguous, trashed, missing or changed
results never silently fall back to another transcript or to raw Run text.

Chat context snapshots bounded quoted transcript data and provenance at enqueue.
The current user instruction remains authoritative; source text grants no tools
or permissions. The recent-message window and total context budget remain in
force. Planner reference context uses a smaller excerpt. Rolling summaries keep
original message coverage offsets and add bounded source excerpts separately;
source Run/artifact/hash and truncation information remain in the summary Run.
Historical snapshots and idempotent turn receipts never change after submission.

The reply exposes which stored transcript supplied context and links back to its
Run. Unavailable sources are labeled rather than invented. Normal provider rules
still apply to follow-up text: selecting an external provider can send that
conversation's transcript text with the user's next question; raw audio is never
sent by this feature. The original CPU transcription itself contacts no LLM.

Acceptance: temporary-database tests for Chat/Work, planner and summaries, source
scope, ambiguity, integrity, Trash, immutable snapshots and bounded/truncated
context; UI provenance checks; one explicitly opted-in local-model follow-up on
the already-approved recording. No cloud or GPU generation runs in normal tests.

The first implementation passes fake-provider conversation and summary regression tests. Real local-model acceptance is a separate deployment check and is not implied by those tests.
