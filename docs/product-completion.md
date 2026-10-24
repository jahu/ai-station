> Saved HTTP/API sources are implemented for explicitly reviewed agent workflows,
> including report preparation and offline local code/data analysis. Authenticated
> reads use server-only credentials and exact policy snapshots; out-of-band key
> changes require review. See [scope and verification](plans/agent-http-connectors.md).
> Release acceptance remains tied to the exact full-gate and deployment reports.

> 2026-10-24: instruction-only CSV/Excel/chart/text creation and bounded earlier
> conversation context are deployed and real-qualified through PRs #404–#406.
> A 131072-context local model used prior values 4, 7, 11, applied the current heading
> override and produced independently checked CSV/XLSX/PNG after one bounded Python
> correction. All 3298 Python cases (3289 pass/nine opt-in skips), 727 UI tests,
> image/Compose and compiled desktop/mobile flows pass. Native Runner and original
> model preset were preserved. See [file creation](plans/local-file-creation.md),
> [conversation context](plans/file-creation-conversation-context.md) and
> `data/acceptance/file-creation-conversation-context-20261024/post-deployment-qualified.json`.
> This completes those workflows; the full-platform objective remains open.

> 2026-10-24 avatar qualification: an ordinary fixed-description agent produced a
> complete five-second 384px/eight-step film from two native Echo windows, using
> the original full-precision models under observed 11-GiB/zero-swap scopes.
> Video/audio decode, coherent face/join samples, actual desktop/mobile-viewport
> playback, source preservation and exact model-preset restoration passed.
> The optional profile, explicit agent setup and measured Standard admission are
> reviewed under [avatar memory loading](plans/echo-memory-loading.md), with
> evidence in `data/acceptance/echo-memory-profile-20261024`.
> This qualifies the recorded short workflow, not all durations or exact lip-sync;
> the whole-platform objective remains open.

> 2026-10-24 delivery: reviewed public research and offline Python analysis for
> persistent agents (#390) are deployed and real-qualified with exact captured
> Coinbase prices and chart. Source scope, original bytes and operator preset were
> preserved. Evidence: `data/acceptance/agent-research-data-20261024/post-deployment-qualified.json`.
> Conversation equivalent #391 is deployed, but real qualification rejected a
> follow-up that invented values after misreading its truncated capture preview.
> [The correction](plans/captured-data-context.md) is deployed as #393; the saved
> capture then returned the checked original prices and chart. The rejected #391
> result is retained. The full platform objective remains open.

> 2026-10-24 functional delivery: natural same-file analysis (#383) and actual
> PNG/Excel/text outputs (#384–#385) are deployed. The real local-model/native
> Python chain checked all six source rows and total150, preserved original bytes
> and restored the operator preset. Qualification:
> `data/acceptance/required-data-exports-20261023/post-deployment-qualified.json`.
> This closes that output workflow, not the full platform objective.

> Agent calendar timezone work reuses existing Tasks/scheduler/worker and adds
> daily-time/custom-cron controls in Agents and the conversation. Existing schedules
> retain UTC through migration 0033. Contract and qualification state:
> [agent schedules](plans/agent-schedule-timezones.md),
> `data/acceptance/agent-schedule-timezones-20261023`. This does not close broader
> orchestration, real long-media or recognition-quality acceptance.

> 2026-10-22 delivery: persistent CSV/XLSX Python agents and results-first agent
> workspaces are deployed (#333–#335). Normal-worker CSV Auto loading/generation/
> execution returned the verified full-file total; see [data agent evidence](python-data-agents.md).
> Code review and follow-ups now share the existing Task inside the agent
> [workspace](agent-workspace.md). Website preview/build policy are deployed (#337–#338).
> Real Local Auto website creation, preview and same-workspace follow-up passed on
> 2026-10-22; evidence: `data/acceptance/agent-website-real-20261022`.
> Deterministic recurring price observations are deployed (#340), including a
> real normal-worker public quote read. Reviewed SMTP and scoped automatic agent
> email are deployed (#342–#343); the optional Finnhub adapter is deployed (#344).
> Public research remains the default for ordinary stock-research instructions;
> account configuration is not required. See
> [market watch](agent-market-watch.md) and [email](reviewed-email.md).

> Current priority override (2026-10-15): [agent-first product plan](plans/agent-first-product.md).
> Deliver local agent code/data execution, agent-oriented results and website
> workflows, followed by real price observations and scoped email delivery.
> Standalone IDE expansion, further Cursor/Codex integrations and full self-development
> acceptance are deferred. The detailed entries below preserve implementation
> history; deferred items are outside this milestone, not newly completed.

Node coding projects now use the existing dependency Run to create missing npm
lockfiles offline from verified public-registry metadata, then install checked
packages and run saved sandboxed build/test commands. Existing locks remain
unchanged. See [Node project dependencies](node-project-dependencies.md).

# Full-product acceptance ledger

[Local music](plans/local-music-generation.md), including direct Chat/Work
dispatch, now has actual queued 10-second instrumental and 30-second
supplied-lyrics GPU/Library acceptance and owned native Stop evidence. The
combined backend/Runner gate passes 2318 tests; release/image qualification is
recorded under `data/acceptance/local-music-generation-20261023`. This is an
optional configured runtime, not a claim that every music duration or quality
profile is qualified. Persistent-agent media tools are delivered through #362–#368.
Original goal-based lyric writing is delivered for persistent agents (#370) and
ordinary Chat/Work (#371). Actual local writing and short GPU WAV/inline/Library
chains passed; subjective sung-word intelligibility remains unverified. See
[conversation music qualification](plans/conversational-music.md).

[Conversation CSV/Excel analysis](plans/conversation-data.md) is deployed (#372),
reusing local Python/data without a persistent Agent or manual repository.
2539 Python/Runner tests, nine opt-in skips, 614 UI tests and compiled desktop/phone
checks pass. Actual Auto model loading with 131072 context and native offline
Python produced the checked full-file total 150, preserved the original input,
and restored the operator model preset. Evidence:
`data/acceptance/conversation-data-20261023/post-deployment-qualified.json`.
Explicit same-file follow-up selection is deployed (#373), with 616 UI tests and
compiled desktop/phone draft/scope/reload checks. The unchanged backend reuses
the actual #372 acceptance. Ordinary CSV/XLSX attachments are deployed (#374), with 624 frontend tests,
compiled desktop/phone first/saved conversation checks and source-identical reuse
of the actual #372 data pipeline acceptance. Evidence:
`data/acceptance/conversation-data-attachments-20261023/post-deployment-qualified.json`.
Ordinary image attachments with local Vision and reference editing are deployed
(#375). Actual local Vision answered the known synthetic image correctly; 2550
Python/Runner tests, nine opt-in skips and 630 UI tests passed. Verified inspected-input follow-ups are deployed in #376, including actual local
Vision reinspection of the same source and model restoration. See
[the image contract](plans/conversation-images.md). Ordinary recording entry is
deployed in #377 with 637 UI tests, compiled desktop/390px checks and actual CPU
Polish WAV transcription followed by a selected-local-model summary. Source/runtime
preservation passed; observed recognition word errors remain quality follow-up.
See [recording conversations](plans/conversation-recordings.md).

Current evidence summary, 2026-10-22: general-agent research, local Python/data
execution and website-building workflows are operational. Public research uses
free search/reviewed public pages and requires no Finnhub key; finance examples
do not define the general agent architecture. A real research agent searched for
`llama.cpp release notes`, wrote an attributed local-model report and was paused
when acceptance finished. Evidence:
`data/acceptance/public-research-real-20261022/result.json`.

Implementation and acceptance remain separate. The dated initial MVP report and
timeline below are historical; their old “future” or “next” labels do not override
the [current implementation handoff](plans/implementation-handoff.md). The ledger
tracks the [agent-first milestone](plans/agent-first-product.md), preserving older
Coding records without making IDE or external coding parity a release requirement.

[Stock-data agents](plans/stock-price-agents.md) add user-owned Finnhub account
configuration, explicit company/symbol lookup, reviewed stock scope and quote
metadata, and reuse deterministic comparison/notice/email delivery. Normal
qualification uses synthetic source/account/SMTP fixtures; a real Finnhub key,
account quote access and external inbox delivery remain unverified.

[Reading a requested website](plans/chat-page-reading.md) is deployed in ordinary
Chat (#341). Explicit URL/bare-domain reading and same-source follow-up passed
real `akademia.ai` acceptance with the local model. Explicit one-turn JavaScript
reading now composes the existing Browser prerequisite, saved screenshot/text
sources and hash-checked follow-ups; release qualification is recorded in
`data/acceptance/chat-rendered-pages-20261022`. [Explicit saved-screenshot Vision](plans/page-screenshot-vision.md)
adds pixel inspection and verified observation reuse through the existing local
tool; qualification is recorded separately. [One-send visual questions](plans/chat-website-design.md) now compose capture and
Vision from a single current-user design question with Web on, without requiring
the advanced JavaScript option. Exact search and text-only overrides remain.
New default-entry qualification is recorded separately; broader visual quality
and multi-step orchestration acceptance remain open.
Text reading alone must not invent observed colors, typography or layout.

Local coding agents can explicitly read reviewed public pages before creating
their worktree/proposal. The same Task preserves fetched sources, approval,
deadline, Stop and conservative recovery. See [reviewed-page coding](agent-page-coding.md).

Named-project Work now resolves explicit Polish/English change instructions to
registered projects and the existing Local Coding Auto flow. Tests cover receipt
replay, frozen policy revisions, ambiguous names, Chat boundaries and Stop; actual
desktop/mobile Send is verified without expensive inference. See
[named-project Work](named-project-work.md).

## Conversation-first entry and useful long media

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
Durable long-media execution is implemented; exact real timing and visual qualification are tracked separately. The original checkout files remain preserved. Name-only Work project creation,
Coding checks/build exports and the focused Memory scope navigation have since
been delivered through isolated reviewed branches; see the current handoff.
The [current implementation handoff](plans/implementation-handoff.md) records
the latest delivered increments and remaining product workstreams. Original checkout WIP is still preserved separately.

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
| Chat and assistant | Streaming compatible providers, selectable stored GGUFs/owned llama.cpp, local/external disclosure, conversation history, summaries, text/PDF attachments, default-on optional web search, typed image/coding/agent/runtime actions, live workstation inspection, bounded planner context, Generate/Edit/Recompose → Upscale, Generate → Video and search → visual brief → image workflows and inline results | Broader multi-step orchestration and practical vision-task acceptance; explicit same-conversation image-result follow-ups now reuse provenance-bound sources (installed 9B pixel inspection verified) |
| Coding and Git | Name-only managed projects, persistent coding sessions, owned worktrees, local/Cursor/Codex bounded proposals, exploration, validation, local repair, cumulative diffs, dependency installation, reviewed commits and approved draft PR publication | Standalone IDE/external coding expansion is deferred by the agent-first decision. Preserve working services; broaden practical local-agent task and model-fit acceptance. 27B long context, React Work, generated-lock continuation and >100 KB source editing are already verified |
| Images and Library | Existing photo pipeline adapter, Generate/Edit/Recompose/Upscale, uploads, thumbnails, annotations, reversible Trash, source/derived lineage and reuse in workspaces/chat; all six initial mode/backend cases passed small real GPU smoke tests | Broader visual quality, performance and supported profile acceptance; qualify newly composed conversation workflows separately |
| Audio, video and avatars | Wan text/image video, CPU Whisper transcription of WAV/MP3/M4A/Ogg/WebM/FLAC, Chatterbox speech and EchoMimic portrait animation adapters, offline ACE-Step music, typed speech → avatar workflows, inline workspaces and artifact playback | Broader runtime/model selection; broader lip-sync, identity and quality profiles. Real 60-second Wan draft and 30-second EchoMimic output are verified at their recorded profiles |
| Agents and workflows | Disabled drafts, explicit activation, durable schedules, child-Run workflows, approvals/retries/notices, Skills, scoped memory, public search/reviewed GET/Browser and GitHub reports; private Local workspaces, offline Python/data processing, website generation/preview/follow-up, deterministic public crypto observations, scoped SMTP delivery and reviewed image/music/speech/whole-video/avatar output | Broader recurring/general-agent composition and real operator-inbox delivery; short agent video/avatar GPU output is qualified at its recorded profile, with broader duration and visual-quality acceptance remaining. Scheduled telemetry/memory/GitHub reports, keyless public research, CSV processing and a concrete website workflow are real-tested; SMTP uses a private test sink |
| Memory | Provenance/scopes, FTS, pin/edit/disable/delete, manual/automatic summaries, agent/workflow observations, explicit linked-project memory retrieval and optional embeddings | End-to-end scope and retention acceptance; retain inspectable retrieval |
| Models and runtimes | Read-only discovery, external observations, owned multi-GPU llama.cpp, loading/unloading, presets, reload/idle eviction, health and restart | Broader runtime adapters; hardware-backed fit/context acceptance for installed models |
| Connectors | Typed registry, permissions, secret references, operational public HTTP GET and GitHub read snapshots (also in Chat/Work); reviewed TLS SMTP with per-message approval and explicitly activated scoped agent email (private-sink qualified) | Real operator-inbox delivery; further GitHub account actions, calendar/social providers and account browser automation |
| Nodes and operations | Portable Docker/native Runner, private socket, password-protected private UI access with independent device sessions, invitation records, backup/check/download, inspectable deployment/lease health; guarded offline restore deployed and disposable-CLI/API qualified in PR #394 | Actual Tailscale enrollment/mobile remote acceptance; broader recovery/rollout reliability acceptance; remote execution-node transport and target-aware execution |
| UX | Dedicated workspaces, default platform assistant, command palette, keyboard/focus support, filters, inspectors and clear execution history | Broader responsive/accessibility acceptance and user-facing wording; compact composer/model catalog/contextual Work paths are delivered |

## Current work

Selected PDF/text/Markdown documents for report, offline code/data and goal-based
media agents are implemented and locally qualified in #411, with upload/Library
selection and source-bound captured text. See [document scope and qualification](plans/agent-document-context.md).
Use its exact-head checks and post-deployment evidence before treating it as live.


Actual longer-media acceptance exists and must not be repeated because an older
plan calls it unfinished. The 60-second Wan draft produced 1440 frames at
1280×704 with four steps; see
`data/acceptance/long-media-20261014/real-result.json`. The 30-second EchoMimic
case produced a fully decoded 384-pixel/eight-step video with audio and browser
playback; see `data/acceptance/long-avatar-default-20261015/result.json`. These
qualify concrete profiles, not cinematic quality or every duration. Recorded
appearance/lighting drift and hand artifacts still need quality work.

[Cursor review](cursor-review.md) records the concrete regressions, fixes and delivery order. Automatic destructive worktree expiry is disabled and SQLite authentication waits no longer freeze the UI. Conversation-first entry, the shared model catalog and retained Coding/Work continuity are delivered. The current handoff identifies the next implementation increment.

The original checkout WIP remains untouched. Its focused Memory scope navigation was ported, simplified, tested and delivered in PR #319; the original files were preserved. Work continues on isolated feature/fix branches, reviewed and locally verified before squash merging into `develop`. `main` and `master` are never deployment targets for autonomous development.

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

2026-10-15 practical React Work acceptance now passes: one natural-language
request created a managed project and selected Local Auto (RVN 27B IQ2_XS, owned
llama.cpp, two GPUs, 131072 context). The first exploration failed on `.gitignore`;
PR #312 fixed that exact root-file contract. A continuation in the same Task and
worktree generated React source, installed checked public npm dependencies,
passed a real Node test of the rendered heading and completed Vite's production
build. Original checkout files and Git index are unchanged. This qualifies that
concrete task/profile, not every website or coding instruction. Evidence:
`data/acceptance/coding-gitignore-20261015/real-result.json` and
`validation-events.json`.

## Recent verified Coding and Memory delivery

- [Continuation after builds](coding-continuation-review.md): actual 27B Work
  follow-up, generated lock review, Node test/build/export, preserved history and
  original checkout. PR #317 is delivered.
- [Larger Local AI source context](local-coding-source-context.md): bounded local
  snapshots/snippet edits, distinct private text-only completion routes and real
  synthetic 110 KB source transport/edit through Work. PR #318 passed 1547
  backend/Runner tests (five opt-in skips) and actual local/Node/build/browser
  acceptance. This is separate from long-context reasoning qualification.
- [Memory scope navigation](memory-scope-navigation.md): Open agent/project and
  filtered run history, 480 UI tests and existing agent-memory navigation on
  desktop/mobile with no workload requests. PR #319 is delivered.

[Independent shot scheduling](parallel-video-shots.md) adds resource-admitted
parallelism, ordered composition/lineage and active-device progress without
weakening RAM reservations. Its verification distinguishes fake GPU/real CPU
concurrency, actual hardware observations and real GPU qualification.
