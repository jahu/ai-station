# One composer for entry and continuing conversations

The immediate entry and existing conversations now reuse `ConversationComposer`:
the same message field, Enter/Ctrl/Command+Enter and IME behavior, collapsed
attachment/tool menu and compact footer. Shift+Enter keeps multiline input;
Enter in a tool input does not accidentally Send the conversation. An active turn
shows Stop while allowing the next draft to be typed, without submitting it.
Existing typed action scopes, turn receipts, cloud disclosure and model loading
are unchanged. Generic regeneration still cannot repeat an orchestration action.

Recent conversations are collapsed on both entry and saved conversation pages.
The saved page uses its conversation title and model rather than an additional
introductory heading. Settings and memory remain reachable in collapsed sections;
the readable transcript and composer get the main workspace. Dedicated tabs and
Coding session history remain available.

The transcript follows new content only while the reader is near the bottom.
Reading earlier messages preserves scroll position during updates; Jump to latest
returns to the current answer. Code, selected text and interactive controls retain
normal keyboard behavior instead of triggering message-list navigation. The whole
token stream is no longer an `aria-live` region.

Verification includes the existing turn/attachment/coding conversation tests,
shared composer tests for shortcuts, composition, tool edits and independent Stop,
and read-only Chromium checks at 1440/390 with a synthetic long transcript and
actual live metadata. The browser check updates the fixture while reading earlier
messages, verifies the unchanged scroll position and Jump to latest, and submits
no workload. Evidence: `data/acceptance/conversation-shell-20261014`.

This advances the [conversation plan](plans/chat-work-experience.md); a unified
provider/model catalog, verified reasoning, session draft persistence, history
pagination and richer contextual Work follow-ups remain separate increments.
It does not claim that long-media or those remaining features are delivered.
