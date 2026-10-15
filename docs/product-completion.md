# Full-product acceptance ledger

## Next priority: conversation-first entry and useful long media

[Unified model catalog](model-catalog.md) now replaces separate happy-path model
and provider selectors in entry, conversations and General settings. Selection is
metadata-only; provider discovery, location disclosure, version guards and old
receipt replay are explicit. Auto Local Coding now selects observed fitting models with verified 100k+ context; owned-model thinking qualification is delivered. Broader task/model policies remain.

[Conversation shell](conversation-shell.md) now shares entry/follow-up composition,
collapses history and tools and preserves reading position during updates. The unified catalog, qualified reasoning, persistent text drafts and contextual Work continuity are delivered; the implementation handoff records their acceptance.

[Create project & build](assistant-project-build.md) now connects a Work name/goal
to owned project setup and the existing isolated coding flow, with explicit
external sharing. Shared Work project/task context and task-wide graph Stop are delivered.

The [first increment](first-send.md) implements immediate first Send, durable
idempotency, settings revisions, remembered new-conversation selection and visible
server-enforced Chat/Work modes. [System/Settings separation](settings.md) is also
implemented. Shared-shell/model selection, verified reasoning and durable longer-media execution are delivered; longer visual-quality profiles remain separate acceptance.

[Local model selection/autoload](chat-model-selection.md) now removes the mandatory
first manual load. A real first-use 9B GGUF completed Chat on both discovered GPUs
in an isolated database, then its owned runtime stopped. Broader model/context
combinations and the remaining conversation-shell work are still separate acceptance.

User direction on 2026-10-14 is captured in the
[implementation brief and handoff](plans/2026-10-chat-work-media.md): immediate
first Send, explicit Chat/Work with media tools, unified model/verified reasoning
selection, distinct System/Settings, and longer Wan/whole-speech EchoMimic output.
The brief defines nine ordered increments and acceptance gates for GPT-6.1-Sol.
Durable long-media execution is implemented; exact real timing and visual qualification are tracked separately. Existing
unfinished Memory and create-project-and-code work
is preserved separately; its integration point is explicit in the handoff.
The [current implementation handoff](plans/implementation-handoff.md) records
the delivered PRs through #303 and remaining product workstreams. Original checkout WIP is still preserved separately.

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
| Chat and assistant | Streaming compatible providers, selectable stored GGUFs/owned llama.cpp, local/external disclosure, conversation history, summaries, text/PDF attachments, opt-in web search, typed image/coding/agent/runtime actions, live workstation inspection, bounded planner context, Generate/Edit/Recompose → Upscale, Generate → Video and search → visual brief → image workflows and inline results | Broader multi-step orchestration and practical vision-task acceptance; explicit same-conversation image-result follow-ups now reuse provenance-bound sources (installed 9B pixel inspection verified) |
| Coding and Git | Name-only managed projects, persistent coding sessions, owned worktrees, local/Cursor/Codex bounded proposals, exploration, validation, local repair, cumulative diffs, dependency installation, reviewed commits and approved draft PR publication | Claude adapter; broader practical coding-task acceptance and fit verification across installed models (27B IQ2_XS long context and basic Coding now verified) |
| Images and Library | Existing photo pipeline adapter, Generate/Edit/Recompose/Upscale, uploads, thumbnails, annotations, reversible Trash, source/derived lineage and reuse in workspaces/chat | Real acceptance for all modes/backends with supported model selection |
| Audio, video and avatars | Wan text/image video, CPU Whisper transcription of WAV/MP3/M4A/Ogg/WebM/FLAC, Chatterbox speech and EchoMimic portrait animation adapters, typed speech → avatar workflows, inline workspaces and artifact playback | Music and broader media runtime/model selection |
| Agents and workflows | Disabled natural-language drafts, explicit activation, durable schedules, child-Run workflows, approvals, retries, notices, Skills, telemetry/scoped-memory/public-search/reviewed-GET and optional isolated public-page Browser tools and inspectable reports and project-scoped Local coding workflows, plus reviewed GitHub reads with local reports | Additional real tools and broader recurring workflows; actual scheduled telemetry/memory reports are verified |
| Memory | Provenance/scopes, FTS, pin/edit/disable/delete, manual/automatic summaries, agent/workflow observations, explicit linked-project memory retrieval and optional embeddings | End-to-end scope and retention acceptance; retain inspectable retrieval |
| Models and runtimes | Read-only discovery, external observations, owned multi-GPU llama.cpp, loading/unloading, presets, reload/idle eviction, health and restart | Broader runtime adapters; hardware-backed fit/context acceptance for installed models |
| Connectors | Typed registry, permissions, secret references, operational public HTTP GET and GitHub repository/issue/PR read snapshots (also in Chat/Work) | Further GitHub account actions, email/calendar/social providers, account browser automation and approvals for consequential actions |
| Nodes and operations | Portable Docker/native Runner, private socket, localhost session protection, invitation records, backup/check/download, inspectable deployment/lease health | Safe restore and rollout; authenticated LAN/node transport and target-aware remote execution |
| UX | Dedicated workspaces, default platform assistant, command palette, keyboard/focus support, filters, inspectors and clear execution history | Broader responsive/accessibility acceptance and user-facing wording; compact composer/model catalog/contextual Work paths are delivered |

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


2026-10-15 real Auto Local coding acceptance: the normal production API and
worker created a name-only disposable project, selected the installed
RVN-IQ2_XS GGUF, loaded it through owned multi-GPU llama.cpp with 131072 tokens,
created arithmetic code and unittest tests in an isolated worktree, and passed
the configured sandboxed validation. Independently repeated unittest validation
passed and the original checkout's files were unchanged. Evidence:
`data/acceptance/local-coding-auto-20261015/result.json`. This qualifies that
concrete task/model profile, not every possible coding task.

2026-10-15 real local Coding acceptance now covers a follow-up through the Work
conversation on the same RVN 131072-token model and preserved task/worktree. Two
observed format failures were fixed: unconstrained prose output and a missing
exploration tool name. Constrained JSON and bounded unexecuted-operation correction
completed the real follow-up, preserved the original add function, implemented
multiply and passed sandboxed plus independent unittest/function checks. Failed
attempts remain in history. Evidence:
`data/acceptance/exploration-repair-20261015/real-retry-result.json`.

2026-10-15: Work planner JSON formatting passed normal production API/worker
acceptance using the configured local qwen3:8b model, parsed a chat plan and
completed the reply without tool/file execution. Evidence:
`data/acceptance/planner-json-20261015/real-planner-verified.json`. Avatar motion
retains bounded causal VAE history; the real 5-second/256/4-step two-window test
passed full audio/decode/timing checks and visual seam inspection. This does not
qualify longer avatar visual-quality profiles. See [Echo motion](echo-motion-context.md).

[Conversational image follow-ups](conversation-media-followup.md) add explicit
reuse of a completed same-conversation result for editing, upscale and animation.
Normal coverage uses temporary images/fake completion, not an unexecuted GPU claim.

2026-10-15: reviewed GitHub reports now support persistent agents. Two real
interval workflows completed all eight Runs, saved scoped memories and retrieved
the first report on the second execution. A final-source one-shot also passed.
Agents were paused after acceptance; see [verification and limits](agent-github-reports.md).

### Offline audio transcription

Delivered implementation: Audio transcription workspace and Chat/Work action,
CPU-only owned Whisper process, bounded WAV uploads, timestamped transcript,
TXT/SRT/JSON artifacts, original lineage and Stop. This does not implement music
or claim every spoken word is correct. Setup and exact verification scope are in
[audio-transcription.md](audio-transcription.md).

Recording questions now compose native CPU transcription and a selected-model answer on one Task/Send, retaining inspectable transcript artifacts on response failure. Verification is recorded in [conversational-audio-analysis.md](conversational-audio-analysis.md); this does not imply music generation or arbitrary audio understanding.

Reversible conversation archiving separates active and archived history/search, keeps old detail URLs, and preserves all execution and memory records. See [archive contracts](conversation-archive.md).
