# One assistant conversation

Product decision, 2026-10-25: remove the user-facing Chat/Work distinction. This
supersedes the two-mode entry in the original brief, `2026-10-chat-work-media.md`
and earlier agent-first acceptance text. Planned; the deployed UI still has the switch.

## Product contract

AI Station opens one composer with model selection and supported reasoning
controls. The user describes a question or desired outcome; the orchestrator
chooses a direct answer, sources, file/image inspection, media, data analysis,
agent preparation or an applicable workflow. Specialist tabs remain available.
Attachments, streaming, artifacts, Stop, follow-ups and history stay in this
conversation. A simple question uses the inexpensive direct response path; it
must not unnecessarily load another planner or create a large workflow.

Show real compact activity and retain model, local/external execution, selected
inputs, approvals and Inspect Run. Do not replace the switch with another
technical mode or obligatory tool choice. Advanced controls remain optional.
Ambiguous consequential requests need focused clarification or concrete action
review; never a “switch to Work” instruction.

## Boundaries and compatibility

- Reuse the current router, assistant, providers and Task → Run → Events →
  Artifacts. Preserve the Docker/native Runner boundary and working executors.
- Route explicit intent deterministically; use bounded model-assisted planning
  when useful. Tools, pages and quoted history cannot grant authority. Derive
  effective permissions from the current request and reviewed scopes, never a
  universal full-access flag on the conversation.
- Keep sensitive-action approvals and explicit agent activation. Removing a
  switch does not silently enable schedules, send mail, publish code, delete
  files or authorize external sharing. Preserve the selected response model and
  verified reasoning. A cloud response provider is not blanket consent to send
  files, screenshots, repository contents or credentials off-machine.
- Preserve conversations, messages, project/agent links, results, continuations,
  unsent drafts, model choices, attachments and request receipts. Opening history
  executes nothing. Old API mode values/records may remain compatibility inputs;
  they cannot recreate the switch or replay earlier instructions in the new UI.
- Introduce an internal assistant policy if needed; honour explicit legacy API
  restrictions for existing clients. The unified UI uses the current policy for
  new turns in both new and saved conversations. Inspect the actual stored column
  before deciding whether a migration is necessary; do not rewrite old modes or
  delete data merely for a new label.

## Implementation order

1. Audit `chat.py`, `assistant.py`, `chat_policy.py`, selected-input agent creation
   and conversation agent controls. Replace mode-only refusals with intent,
   scope, provider and permission checks. Preserve direct response/reasoning and
   compatible serialization, idempotency and lost-ack recovery.
2. Remove `ChatModeSwitch` from `NewChat`, `Chat` and General settings. Remove the
   visible default-Chat/default-Work preference. Migrate browser drafts without
   losing typed text, selected models or attachments.
3. Replace mode-specific hints/errors, including data controls and agent actions.
   Natural requests must reach existing capabilities from the single composer.
4. Finish [media language and inline recovery](conversation-prompt-language.md)
   inside this unified UI. Do not add new Chat/Work variants. Retries must show
   the actual result after refresh while preserving the current draft.
5. Update current help/status documentation and Polish QA cases; retain historical
   release evidence. Run local gates, review, PR to develop, backup/deploy and
   data-preservation verification. No direct main/master push or merge.

Acceptance: new/saved conversations, ordinary replies, optional default-on Web,
direct page reads, image/media/data requests, agent draft/run/stop, local code
workflows, model reasoning, attachments/follow-ups, approvals, Stop and frozen
retries. Verify local/external response-provider branches without hidden sharing,
old drafts/history, reload, lost acknowledgements and no execution on inspection.
Compiled desktop/phone checks must show no switch or requirement to switch to Work.
The final operator QA workbook must describe this one-chat workflow; handoff waits
for its implementation and qualification.
