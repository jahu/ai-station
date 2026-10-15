# Reversible conversation archive

Conversation history distinguishes active and archived conversations.
Archive preserves every message, Task, Run, artifact and memory. Restoring makes
the conversation available for follow-ups again. No destructive conversation
Delete or cascading cleanup is introduced.

Store nullable archived_at via Alembic migration. Archive/restore require an idle
conversation and its expected settings revision; the same write advances that
revision. A concurrent stale Send or settings edit must fail rather than restart
an archived conversation. Existing Run ownership and Task Stop stay unchanged.

Default history/search lists active conversations; an explicit Archived view lists
archived matches with the same cursor and search bounds. Archived detail remains
readable through its old URL and offers Restore. Sending, regeneration, summaries
and work selection require restoring first. UI actions use existing errors/loading
states and invalidate only conversation history/detail; opening Archive never
executes a model or deletes related work.

Acceptance: upgrade existing database data; archive/restore version conflicts;
active-Run guard; default/archived history and search/cursors; rejected Send with
no new receipt/messages/Task; preserved artifacts and memory; frontend restore and
archive navigation including errors, keyboard and mobile layouts.
