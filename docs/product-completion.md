# Full-product acceptance ledger

## Next priority: conversation-first entry and useful long media

[Conversation shell](conversation-shell.md) now shares entry/follow-up composition,
collapses history and tools and preserves reading position during updates. Unified
catalog, reasoning, persistent drafts and contextual Work continuity remain next.

[Create project & build](assistant-project-build.md) now connects a Work name/goal
to owned project setup and the existing isolated coding flow, with explicit
external sharing. Shared conversational project context and task-wide graph Stop
remain separate follow-up work.

The [first increment](first-send.md) implements immediate first Send, durable
idempotency, settings revisions, remembered new-conversation selection and visible
server-enforced Chat/Work modes. [System/Settings separation](settings.md) is also
implemented. Shared-shell/model
picker refinement, verified reasoning and longer media remain next increments.

[Local model selection/autoload](chat-model-selection.md) now removes the mandatory
first manual load. A real first-use 9B GGUF completed Chat on both discovered GPUs
in an isolated database, then its owned runtime stopped. Broader model/context
combinations and the remaining conversation-shell work are still separate acceptance.

User direction on 2026-10-14 is captured in the
[implementation brief and handoff](plans/2026-10-chat-work-media.md): immediate
first Send, explicit Chat/Work with media tools, unified model/verified reasoning
selection, distinct System/Settings, and longer Wan/whole-speech EchoMimic output.
The brief defines nine ordered increments and acceptance gates for GPT-6.1-Sol.
Remaining increments are planned; no new long-media success is claimed. Existing
unfinished Memory and create-project-and-code work
is preserved separately; its integration point is explicit in the handoff.
The [current implementation handoff](plans/implementation-handoff.md) records
`develop` f7387bf, the adapted uncommitted Work project-build branch and the
remaining shell/catalog/reasoning/media gates. Planning does not merge that WIP
or qualify longer GPU output.

Coding supports checked removal of selected source files, explicit Deleted
review labels, cumulative follow-up patches and separate reviewed commits.
Repairs cannot introduce deletions. See [source removal](coding-file-removal.md)
for the fake-provider/disposable-Git verification scope.

Real scheduled-agent acceptance on 2026-10-14 completed two interval workflows
using existing qwen3:8b inference and actual workstation observations. Eight Runs
succeeded; both reports retained agent-scoped memory with source provenance, and
the second workflow retrieved the first report. Desktop/mobile rendered the real
report. The acceptance agent was paused afterward. Evidence:
`data/acceptance/scheduled-agent-20261014`. This does not prove other tool schedules.

Worker execution uses three configurable, independent process slots. Tests
cover short work completing during a held long Run, exclusive GPU reservation,
lease renewal, cancellation and supervisor shutdown/crash handling. This is
concurrency coverage with fake executors, not a claim that several real model
servers or GPU workloads were stress-tested together.

The target is the complete AI Station vision, reconfirmed on 2026-10-13. An implemented capability is complete only after its UI, persistence, permissions, cancellation/recovery, artifacts and applicable real integration are verified. A passing fake adapter test is not a real hardware smoke test.

| Workstream | Implemented | Remaining delivery and acceptance |
| --- | --- | --- |
| Shared execution | Durable Tasks, Runs, events/SSE, artifacts, worker leases, recovery, scheduling, approvals and resource locks | Extended reliability under sustained concurrent use; end-to-end acceptance for every enabled adapter |
| Chat and assistant | Streaming compatible providers, selectable stored GGUFs/owned llama.cpp, local/external disclosure, conversation history, summaries, text/PDF attachments, opt-in web search, typed image/coding/agent/runtime actions, live workstation inspection, bounded planner context, Generate/Edit/Recompose → Upscale, Generate → Video and search → visual brief → image workflows and inline results | Broader multi-step orchestration, and practical vision-task acceptance (installed 9B pixel inspection verified) |
| Coding and Git | Name-only managed projects, persistent coding sessions, owned worktrees, local/Cursor/Codex bounded proposals, exploration, validation, local repair, cumulative diffs, dependency installation, reviewed commits and approved draft PR publication | Claude adapter; broader practical coding-task acceptance and fit verification across installed models (27B IQ2_XS long context and basic Coding now verified) |
| Images and Library | Existing photo pipeline adapter, Generate/Edit/Recompose/Upscale, uploads, thumbnails, annotations, reversible Trash, source/derived lineage and reuse in workspaces/chat | Real acceptance for all modes/backends with supported model selection |
| Audio, video and avatars | Wan text/image video, Chatterbox speech and EchoMimic portrait animation adapters, typed speech → avatar workflows, inline workspaces and artifact playback | Music, transcription and broader media runtime/model selection |
| Agents and workflows | Disabled natural-language drafts, explicit activation, durable schedules, child-Run workflows, approvals, retries, notices, Skills, telemetry/scoped-memory/public-search/reviewed-GET and optional isolated public-page Browser tools and inspectable reports and project-scoped Local coding workflows | Additional real tools; real recurring-task acceptance |
| Memory | Provenance/scopes, FTS, pin/edit/disable/delete, manual/automatic summaries, agent/workflow observations, explicit linked-project memory retrieval and optional embeddings | End-to-end scope and retention acceptance; retain inspectable retrieval |
| Models and runtimes | Read-only discovery, external observations, owned multi-GPU llama.cpp, loading/unloading, presets, reload/idle eviction, health and restart | Broader runtime adapters; hardware-backed fit/context acceptance for installed models |
| Connectors | Typed registry, permissions, secret references and operational public HTTP GET connectors | GitHub integration beyond coding publication, email/calendar/social providers, browser automation and approvals for consequential actions |
| Nodes and operations | Portable Docker/native Runner, private socket, localhost session protection, invitation records, backup/check/download, inspectable deployment/lease health | Safe restore and rollout; authenticated LAN/node transport and target-aware remote execution |
| UX | Dedicated workspaces, default platform assistant, command palette, keyboard/focus support, filters, inspectors and clear execution history | Compact conversation controls, simpler common paths, responsive/accessibility acceptance and user-facing wording |

## Current work

[Cursor review](cursor-review.md) records the concrete regressions, fixes and delivery order. Automatic destructive worktree expiry is disabled and SQLite authentication waits no longer freeze the UI. Current changes simplify Chat without removing advanced settings or explicit grants.

The original checkout contains preserved unfinished Memory changes; they are not silently included in deployed releases. Work continues on isolated feature/fix branches, reviewed and locally verified before squash merging into `develop`. `main` and `master` are never deployment targets for autonomous development.

The platform assistant remains the primary experience, with dedicated workspaces as direct entry points. Its execution model is described in [orchestrator.md](orchestrator.md). Real integrations remain visibly unavailable until implemented and verified; credentials or downloads are never invented to make an acceptance row appear complete.

The 2026-10-13 model acceptance completed a local 27B load at 131072 context, a synthetic 110029-token Chat input and a real isolated Coding task with passing unittest validation. See [model context](model-context.md). Local pixel vision is implemented and real-tested with the installed 9B GGUF/projector pair; see [Chat vision](chat-vision.md).


2026-10-13: public-page Browser now follows normal native Run dispatch and
permission/ownership/cancellation/recovery contracts. Agent history adopts rendered
text and Library screenshots; account browser automation remains a separate future
connector capability. Real Chromium/native acceptance and fake-provider agent
acceptance are distinguished in [browser verification](browser.md).
