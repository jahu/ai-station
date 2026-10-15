# Searchable conversation history

Conversation history stays visible beside the transcript on desktop and opens
as a drawer on phones. Search conversation titles and persisted message text, or
**Load older conversations** past the initial 100. Search is read-only and includes
older conversations even when they have not been loaded in the current UI.

The existing `GET /api/chat/conversations` array response stays compatible. It
accepts optional `q` (200 characters) and the paired `before` / `before_id`
(timestamp and UUID) cursor. Results are ordered by descending update time and
UUID, at most 100 per page. The cursor records the last observed tuple, so a new
conversation inserted ahead of a loaded page does not shift its older boundary.
Search treats SQL wildcard characters as literal input and never enqueues Runs.
Edited conversations may move earlier; the UI deduplicates records by identity.

Temporary-database tests cover 205 tied timestamps, new-arrival pagination,
message-content/title search, literal wildcard handling and cursor validation.
Frontend tests exercise loading the next page and search. Dedicated workspace
navigation and conversation drafts remain intact.
