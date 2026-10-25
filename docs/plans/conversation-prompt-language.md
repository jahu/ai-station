# Conversation media language and inline recovery

Implemented and locally qualified within unified assistant PR #444, following
shared media translation PR #443. Per-turn policy and inline review/recovery use
the same media creation services. See the qualification and deployment authority
in the [single-assistant plan](unified-assistant-chat.md).

Priority update, 2026-10-25: implement this inside the
[single assistant conversation](unified-assistant-chat.md). “Chat/Work” below
describes existing records and compatibility coverage, not two future UI modes.
Removing the switch and mode-only refusals precedes final handoff.

- Add an optional per-turn media translation scope to the existing conversation
  request and tool-options draft. Absence keeps the exact previous serialization
  and receipt identity. Reuse the existing translation controls inside media tool
  options, without cluttering the main composer or translating ordinary replies.
- Forward the explicit override only after selecting image/video/music execution.
  The original user message, selected references, provider and all execution
  settings remain unchanged. Lyrics and speech are excluded. Existing local
  translator preparation/review/resources/Stop contracts remain authoritative.
- Inline recovery must follow the actual returned retry in the conversation,
  including after refresh; changing only a workspace `?run=` query is insufficient
  for a conversation-bound result. Follow a bounded, verified saved retry chain
  (same Task/executor, expected parent), retain earlier attempts and show errors
  instead of displaying unrelated or cyclic results.
- Reuse existing typed retry endpoints and durable UUID receipts. Failed or lost
  acknowledgements cannot silently create another Run. Recovery preserves the
  conversation, unsent draft, model/tool choices and attachments. Merely viewing
  history or following an existing retry performs no execution.
- Verify new/saved Chat and Work, explicit on/off versus global defaults, ordinary
  chat unaffected, approval/edit, failed translation → original/retry, inline
  result after refresh, source-bound chain rejection and composer preservation.
  Include desktop/phone compiled acceptance, existing full local checks and QA
  cases before review/merge/deploy. No native API or database schema changes.
