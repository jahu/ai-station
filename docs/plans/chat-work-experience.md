# Chat and Work: UX, policy and implementation contracts

Status: partially delivered, 2026-10-14. Part of the [delivery brief](2026-10-chat-work-media.md).
The findings below describe the original **806b604** baseline. Immediate first Send,
mode policy and typed defaults now exist; local model selection is independent of
loading. Use [first-send contracts](../first-send.md) and
[model selection](../chat-model-selection.md) for those delivered APIs. Other new
schemas/components below remain proposals. The [updated handoff](implementation-handoff.md)
defines the remaining work against **f7387bf**; do not reproduce completed changes.

## 1. Findings in the current code

| Location | Actual behavior | Required change |
| --- | --- | --- |
| `frontend/src/App.tsx` | `/`, `/chat` and `/chat/:id` all render `Chat assistant` | Keep URLs, introduce an immediate blank composer and a shared conversation shell |
| `frontend/src/pages/Chat.tsx` | No-ID branch renders SettingsForm and Create conversation; conversation has a separate composer | Share one composer across new/existing conversations; create on first Send |
| `ChatSettingsChoiceLists.tsx`, `TurnModeChoiceList.tsx` | Saved local/orchestrator mode plus three this-turn overrides, hidden in settings | Expose two consistent Chat/Work choices; keep old wire aliases compatible |
| `LlamaModels.tsx` | Existing GGUF/catalog picker mixes selection with GPU/context/load/restart controls | Reuse discovery and runtime services, separate simple selection from runtime inspection |
| `backend/app/chat.py` | Local mode rejects all capability actions/image-artifact references; orchestrator handles them | Chat needs its own enforced allowlist for media tools, not just a renamed local label |
| `assistant.py`, `AssistantActions.tsx` | Rich typed actions, inline artifacts, sources, coding/agent controls already exist | Retain dispatch/services; show contextual cards instead of all action forms |
| `local_provider.py` | Streams final text/tool calls; no reasoning request contract | Add verified optional generation controls and distinct bounded reasoning/status handling |
| `local_model.py` / `vision_messages.py` in Runner | Strict Completion/VisionCompletion payloads, output max 8192 | Update both typed paths deliberately; never pass arbitrary provider JSON |
| `llama_runtime.py` | Owned runtime launch forces `--reasoning off --reasoning-budget 0` | Capability-aware request settings require a tested runtime policy, not just UI fields |

The live entry was visually inspected. It has a global sidebar plus a large
conversation-history column, introductory heading, raw endpoint and configuration
card, but no question input until a conversation is created. These are the main
happy-path obstacles. Preserve working history, SSE, Markdown, artifacts and tools.

## 2. Screen and interaction specification

### Empty entry

Keep the left workstation navigation and a compact **New chat** action. The main
area is a calm, centered prompt, roughly 720–840 px wide on a desktop, with the
composer ready for typing. Suggested starting prompts are optional and at most
three; selecting one inserts text without sending. No endpoint, GPU index, title,
Run ID, permission matrix or Create conversation button appears here.

```text
Existing navigation  |                         AI Station
                     |                 What would you like to do?
                     |
                     |        [ Chat | Work ]  [ Model ▾ ] [ Thinking ▾* ]
                     |        ┌─────────────────────────────────────────┐
                     |        │ Ask a question or describe a task…      │
                     |        │                                         │
                     |        │ [+] [Search web: off]             [↑]   │
                     |        └─────────────────────────────────────────┘
                     |                       * only when supported
```

Default is Chat on first visit. Subsequently use the last explicit preference;
show the selected mode prominently. `/` and `/chat` without an ID both start a
new draft; opening a stored ID restores that conversation. New chat clears its
content/scope while retaining explicit model/mode preferences. No empty conversation
row is created by navigation, opening the picker or typing.

### During a conversation

The same composer moves below a readable transcript. Header shows editable title,
model, Chat/Work and an overflow menu for advanced settings. Keep the composer
sticky within the conversation area; avoid nested transcript/page scroll traps.
Use `100dvh` and mobile safe-area padding. History becomes a collapsible section
of navigation or a drawer, not a permanently separate wide column. Preserve
conversation and Coding session links; history search/paging must reach older
items beyond the current 100-conversation list.

Text appears incrementally. A compact status row explains Waiting for GPU,
Loading model, Searching, Generating image, Writing changes, Running tests, etc.
It reflects persisted events, not guessed percentages. One **Stop** controls the
active turn's owned work, including child transitions. Keep completed/partial
results visible after cancellation; failures appear on the affected turn with a
specific retry/repair path. Never display Done merely because routing finished.

Autoscroll only while the reader is near the bottom. When they scroll up, keep
their position and show **Jump to latest**. Do not announce each token through a
live region; announce stage changes and completion. Standard text selection and
arrow navigation inside the textarea/code must work. Put keyboard explanations
in help/tooltips rather than repeated paragraphs in every list.

### Composer and attachment behavior

- Send on Enter, newline on Shift+Enter; respect IME composition and user send-key
  preference. Mobile has an explicit Send. Disable duplicate submission while
  preserving the draft on transport error. Streaming Stop replaces Send only for
  that active turn; allow typing the next draft without auto-submitting it.
- One attachment menu supports upload, paste, drag/drop and Library reuse.
  Show thumbnails, filename/type, upload progress and removal before Send.
  Preserve image order and roles such as person/clothing; do not reorder by UUID.
- Support existing bounded text/PDF/image/WAV contracts. State PDF extracted-text
  limitations where relevant. Do not send image pixels to a text-only endpoint,
  silently ignore an image or describe it as understood merely because it is stored.
- For a requested visual task, route to a verified local vision/media adapter.
  Show the actual processing model on the result when it differs from the selected
  conversation model. External vision transfer requires explicit consent to those
  images; it is never an automatic fallback.
- Search web remains a compact, off-by-default toggle. Reveal a query override in
  its popover; retain sources/date next to the answer. It authorizes public search,
  not arbitrary browser access or uploading conversation history to a search engine.
- Present unknown/unsupported attachment types and exceeded bounds inline with an
  actionable message. Preserve other attachments/draft when one upload fails.

### Result presentation

Reuse artifact IDs and lineage; build shared cards for image, video, audio, file,
code review, project and agent draft. Image opens a lightbox; video/audio plays
inline; file has Download/Open in Library; coding shows summary, changed files and
checks with expandable diff. Large code/documents may use an optional right-side
inspector on desktop and a drawer on mobile. No second artifact storage system.

Keep Inspect Run and advanced parameters in a secondary menu. Do not repeat the
same artifact under every parent/child. Tag intermediate previews as such; one
final result is prominent. Creating an agent shows its editable disabled draft;
activation stays explicit. Git commit, publication, destructive changes and
external disclosure retain their existing concrete review/approval controls.

## 3. Model and reasoning selection

### One model picker

Normalize the existing provider registry, local-server discovery and `/api/llama`
catalog into a read-only model catalog (proposed `GET /api/chat/model-catalog`).
Each item has a stable `model_ref` (provider + existing model key), display name,
location, runtime label, availability/loading state, supported modalities and
capability provenance. A local GGUF retains its `llamacpp:<ModelFile.id>` identity.
Do not substitute a filename for identity or infer capabilities from its name.

Group by **Local · llama.cpp**, **Local server** and **External**, with search and
short badges such as Ready or Loads when needed. No manual model text field on
the normal path. Unknown provider model IDs remain available in Advanced for
explicit setup, not guessed by the assistant. Include installed compatible models
even when unloaded; unavailable models show a reason and a Settings/Models link.

Selecting an unloaded model saves a preference, not a load Run. First Send uses
existing `prepare_consumer`/owned runtime dependencies and records the load stage.
Auto chooses deterministically from enabled local candidates using task modality,
known context fit and availability, honoring an explicit pinned model. Do not
force the largest model or 100k context for a greeting. Coding can retain its
larger-context profile. GPU/context/cache controls remain in Models/advanced
inspection, with requested and actual values accessible after execution.

Do not fall back to cloud when local memory is busy or a local endpoint fails.
Offer a user-selected alternative. External items are visibly external before
selection and Send; snapshot the selected endpoint/config version and disclosure
scope. Change during streaming applies to the next turn only, not the active Run.

### Reasoning is a capability, not a universal slider

Proposed normalized capability: `reasoning.kind = unsupported | toggle |
native_effort | token_budget`, supported values, default, runtime/build/template
identity, verification state and effective limits. Only a verified combination
gets a control. Unknown means no control. All fields are server-validated.

| Verified capability | UI | Wire contract |
| --- | --- | --- |
| None/unknown | No reasoning selector | Omit extra fields; retain working defaults |
| Thinking toggle | Thinking: Off / On | Adapter maps only the supported typed boolean |
| Native effort | Effort: model-supported choices | Use that provider/template's exact supported enum; no fabricated High option |
| Token budget only | Thinking budget with clear bounded presets | Map to verified token-budget support; do not label this native effort |

llama.cpp upstream documents reasoning controls and chat-template parameters;
support varies by runtime build and template. This is evidence to investigate,
not proof that the deployed image accepts every field. See its
[official server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
Pin the inspected build/template in the acceptance record before enabling a mapping.

Implementation must address the existing hardcoded reasoning-off launch flags.
First test whether the installed build permits a request override. If it does,
keep an explicit safe default and pass typed per-turn settings. Otherwise qualify
an owned runtime profile with a compatible default and explicit per-request off;
replace/restart it only through managed runtime lifecycle when idle. Never alter
an external server. Do not offer On while the runtime still forces budget zero.

Snapshot requested and effective reasoning, output budget, context fit and model
identity in each Run. Thinking consumes time and usually context/output allowance;
validate the combined envelope for that provider, leaving room for a final answer.
Do not globally raise the current 8192 output-token limit or confuse output length
with context capacity. The local Coding collector currently requests bounded JSON
and `/no_think`; preserve its tested behavior independently of Chat preferences.

Streaming must tolerate reasoning-only chunks before final content and surface
working status rather than an empty answer. If the provider exposes an eligible
reasoning summary/trace, render it separately, bounded and collapsed; never invent
a thought narrative or treat reasoning as final answer/tool authorization. Do not
reinsert it into normal conversation context by default. A token-limit finish is
an incomplete result with an honest continuation option, not silent success.

## 4. Chat/Work server policy

Do not use a prompt as the enforcement boundary. Resolve a versioned mode policy
before routing and intersect its capabilities with explicit tool selections,
project scope, installed adapters and existing effective permissions. Repeat the
check after model planning and before child publication. UI hiding is insufficient.

| Action family | Chat | Work |
| --- | --- | --- |
| Text Q&A, code explanation/snippets, attachments | Yes | Yes |
| Web search | Only explicit per-turn opt-in | Same |
| Image understanding; requested Generate/Edit/Recompose/Upscale | Yes, typed media scope | Yes |
| Requested video, speech or avatar | Yes, same resource/cost controls as dedicated workspace | Yes |
| Read existing artifact for the conversation | Explicit attachment/selection | Same |
| Write a project, run tests, create a repository/worktree | No; offer Switch to Work retaining draft | Yes, scoped to selected/confirmed project |
| Create/manage persistent agents | No; may explain or draft text only | Disabled definition creation; explicit enable/edit grants |
| Git commit/push/PR; manual model/runtime control; station maintenance | No | Only existing explicit action/policy/approval, never automatically from Work |
| Owned model autoload needed for an allowed inference/media action | Yes through existing resource services | Same |

Chat is a conversation with bounded tools, not a free-form workstation agent.
For "implement this feature" in Chat, explain the required Work mode and show one
switch action; do not silently execute, lose the prompt, or claim implementation.
For ambiguous requests, ask one focused question in the transcript. A webpage,
attachment, remembered preference or old Work turn cannot promote a Chat turn.

The delivered canonical UI/API values are `chat|work`. Legacy `local` and
`orchestrator` remain accepted with their existing behavior; **local is not a raw
alias for the new media-enabled Chat policy**. Preserve this compatibility rather
than silently widening old clients' permissions. Historical Runs retain recorded
mode/policy. `auto` for an old per-turn override means inherit the saved mode,
never escalate permissions.

## 5. Durable first-send and conversation settings

The first-turn endpoint is delivered. Its current field names are shown below;
reasoning and a unified model reference will be additive future changes, not a
replacement endpoint. See `TurnBody`, `ConversationBody` and `MessageBody` in
`backend/app/chat.py` before implementing extensions.

```json
{
  "client_request_id": "uuid",
  "conversation_id": null,
  "expected_settings_version": null,
  "selection": {
    "execution_mode": "chat",
    "provider": "local-openai-compatible",
    "model": "existing-model-key"
  },
  "content": "Explain this function",
  "attachments": [],
  "execution_mode": "chat",
  "web_search": {"enabled": false, "query": ""}
}
```

Use typed selected artifact IDs/options from current validators, not arbitrary
tool JSON. Current receipt response: `conversation_id`, `user_message_id`,
`task_id` and serialized `run`. Any additional resolved-selection fields must be
additive. A new conversation, immutable user turn and queued work commit
in one short DB transaction. Provider/model metadata validation may precede it;
inference, model loading, filesystem project work and media processing do not run
inside the HTTP handler. Reuse refactored enqueue services instead of internally
calling another HTTP handler or building a second chat pipeline.

Store a unique client request receipt with canonical payload digest and response
identities. Alembic **0020** already adds `chat_turn_requests`: request UUID,
payload hash, conversation/message/task/run references and created_at. Same UUID
+ same body returns the original receipt; same UUID + different body is 409.
Claim it transactionally before creating domain rows. Two tabs with distinct
requests still obey one active turn/workflow per conversation. Timeout/reload
retries use the original UUID; explicitly sending another prompt uses a new UUID.
Retain receipts as long as their turn exists. Do not hash/store secret values.

Stage binary uploads through existing validated storage before enqueue; turn
acceptance links artifact IDs. For existing inline text/PDF attachment handling,
avoid duplicate durable files across idempotent retries. On validation failure
roll back rows and clean only known unreferenced staging files; never delete a
Library artifact. Navigation alone creates neither uploads nor conversations.

Conversation `settings_version` is already delivered in **0020**. Any future
bounded `generation_settings` field requires a new migration; never edit 0020 to
add reasoning retroactively. Existing columns continue to hold provider/model/mode
and normal sampling settings. New global defaults use a typed versioned value in
existing `Setting`, e.g. `conversation_preferences`; do not add a generic editable
JSON settings endpoint. Defaults affect future drafts, not historical turns.
Validate expected settings version so stale tabs cannot overwrite each other.
Per-turn selection is snapshotted; saving a default or changing model while typing
must never mutate active Run parameters. Initial defaults can preserve existing
reasoning-off behavior until the verified reasoning milestone is delivered.

Use deterministic title from the first prompt, reusing current behavior. No paid
LLM call just for naming. Persist unsent text/selection in session-scoped draft
storage with clear-on-send/logout and bounded lifetime; do not persist secret
inputs or binary attachments in localStorage. Upload references must be revalidated
on restore. Keep earlier chat endpoints as adapters during migration.

## 6. Work context and ongoing tasks

Work is the orchestration entry; Coding is its focused repository/diff/checks
workspace. Agents are saved recurring or manual definitions. They share Runs,
but a Coding session is not automatically a persistent Agent.

Display a compact context chip for the selected project and ongoing coding Task.
A follow-up such as "now add login" continues that explicit session/worktree via
existing follow-up services; show New task as an explicit alternative. If multiple
candidate projects/tasks exist, ask which one. Never pick a repository just from
untrusted attachment text or a stale previous conversation. Backend revalidates
Task/project/worktree ownership and current versions on every continuation.

Fold the existing `.tools/assistant-project-build` work into this experience after
review: "Create project Weather and build ..." should create the owned project and
then use the existing worktree/proposal/check flow. Ask only for a missing name or
goal. Agent/model choice lives on the contextual card: Auto/Local, Cursor, Codex
with real available model choices. Defaults stay local; selecting an external
executor requires the existing concrete disclosure scope. No automatic commit,
push, PR, activation or deployment follows a model's successful answer.

Task status must cover model load, setup, worktree, coding, validation and repair.
Use one compact stage list, with technical details expandable. A successfully
created project remains usable if coding later fails; retain the failed stage and
retry/repair path. The transcript links the identical Coding session rather than
cloning its state. Stop addresses all owned in-flight children of that turn.

## 7. Code map and acceptance

Frontend: evolve `Chat.tsx` into a thin route/container plus shared
`ConversationShell`, `Composer`, `ModelPicker`, `ModeSwitch`, `Transcript` and
`TaskResultCard` components. Reuse `LlamaModels` catalog helpers, `ChatWebSearch`,
artifact players, Library picker and existing approval/review components. Extract
only touched responsibilities; do not rewrite unrelated pages or every list.
Keep React Query keys/SSE invalidation consistent across Chat, Coding and Library.

Backend: `chat.py`, `assistant.py`, `chat_providers.py`, `chat_executor.py`,
`local_provider.py`, `models.py`, migrations; small shared mode-policy/catalog/
turn-service modules as needed. Runner changes for reasoning belong in
`local_model.py`, `vision_messages.py`, `llama_runtime.py`, not general-purpose
payload forwarding. Remove now-false text in `local-chat.md`, attachment labels
and `orchestrator.md` when the corresponding behavior changes.

| Case | Acceptance scenario |
| --- | --- |
| C1 | Fresh `/`: type and Send without setup; one persisted conversation/Task; streamed answer; browser refresh retains it |
| C2 | Double click/network timeout/retry and two tabs: no duplicate first message, artifacts, project or side effects; differing reused request UUID rejected |
| C3 | Change among configured local GGUF/local-server/external models; unloaded local loads only on Send; actual model shown; no silent cloud fallback |
| C4 | Chat image upload + question, two ordered images + clothing edit, Library reuse, optional public search with sources; task results inline |
| C5 | Coding/agent/runtime mutation attempted in Chat via UI and crafted API/model plan is denied before dispatch; switching to Work retains draft but does not send |
| C6 | Work new project + goal, existing project follow-up, checks failure and repair; same worktree/context; scoped external consent and reviewed Git actions retained |
| C7 | Reasoning toggle/native effort on a verified installed model affects outgoing payload; unsupported model hides it; reasoning-only stream, budget exhaustion and final output handled |
| C8 | Stop during load/inference/media/setup and at parent→child boundary; refresh/resume SSE without duplicate text; completed artifacts preserved |
| C9 | Desktop/mobile/zoom/keyboard, pasted files, long code, large artifact, slow/offline provider, missing model; user can scroll back while streaming without jumps |

Unit/integration tests must cover server policy and transactional/idempotency races,
not just visible labels. Test migrations on a database containing old conversation
modes and messages. Fake stream tests include content, reasoning, tool and empty
chunks. Use real local smoke only for the verified runtime mappings and final UX;
do not consume external tokens merely to test picker layout.
