# Immediate conversation entry

The entry at `/` or `/chat` has a message composer, local model selection and
visible Chat/Work controls. Send creates the conversation and queues its first
turn together. Browsing, choosing a mode or typing creates no conversation.
Recent conversations remain available in a collapsed history section.

Chat supports conversation replies, explicit optional web search and requested
image/video/speech/avatar actions through existing executors. Work adds the
existing scoped coding, project, agent and owned-runtime actions. The server
rejects explicit Work scopes in Chat and constrains routing results before any
child is published. A natural project-creation instruction in Chat asks the user
to switch to Work. Work still requires concrete coding/Git/cloud scope and review;
the mode grants no universal permission.

`POST /api/chat/turns` accepts a UUID `client_request_id`, a `selection` using the
existing conversation schema for a new conversation, and the existing typed
message/action fields. For an existing conversation, send `conversation_id` and
its `expected_settings_version`, omitting selection. Settings revisions prevent
a stale turn from silently using changed model settings.

Alembic `0020` adds a conversation settings revision and durable request receipts.
Identical retries return the same conversation/message/Task/Run; changing a body
under an accepted request UUID is rejected. Creation, message/attachments, queued
work, receipt and last new-conversation preference commit in one transaction.
All inference and host work remain in workers. A successful Send resets the UI
request identity; another intentional message receives a new UUID.

`GET/PUT /api/chat/preferences` exposes typed mode/model/provider/send-key defaults
in existing Settings storage with optimistic revisions. New conversations remember
the last accepted explicit selection. These preferences never rewrite historical
messages or active Run parameters. External providers remain explicitly selected
and visibly external. No reasoning control is exposed before its runtime mapping
is verified.

Legacy conversation URLs and local/orchestrator API modes remain supported. Old
messages are preserved. Capability actions cannot be repeated through generic
completion regeneration; the user sends a new instruction instead.

Verification uses temporary databases and fake inference, covering atomic first
Send, concurrent identical retries, restart/replay, attachments, stale settings,
preferences, denied Work actions and existing media dispatch. Browser checks of
the production build use live read-only model/hardware metadata fixtures and
submit no real workload. Actual deployment/local inference acceptance is recorded
separately under `data/acceptance/chat-first-turn-20261014`.

This is the first increment of the [conversation and long-media plan](plans/2026-10-chat-work-media.md).
The next increments refine the shared conversation shell/model picker, split
System/Settings and qualify reasoning/long-media execution.
