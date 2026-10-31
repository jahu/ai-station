The Linux desktop packaging candidate bundles a relocatable real CPython,
native Runner and compiled Docker image around the existing supervisor. Its
private configuration selects a separate data root, Compose project and exact
application image; no second application API is introduced. Installed code is
copied into a retained version directory before supervision so OS package
replacement cannot remove running native code. [Desktop contract](plans/desktop-installation.md).

The desktop owner can supervise in the background without keeping a window
open. A private same-OS-user control socket supports only status and
instance-bound Stop; the existing supervisor remains responsible for shutdown.
It is outside the HTTP application and its container data mount. This adds no
workload executor, native Runner endpoint or login/reboot service.

Guided local runtime preparation now reuses owned Tasks/Runs, a native immutable
operation journal and a bounded child over the local Docker Unix API. The child
streams only one reviewed image digest, records actual layer progress and verifies
its source/platform before a private receipt is published. Worker lease recovery
reattaches that operation; revoked-owner cleanup has separate trusted cancellation
coordination. [Setup contracts](plans/guided-model-installation.md).

Guided conversation-model setup uses the [reviewed installation catalog](plans/guided-model-installation.md), ordinary owned download Tasks/Runs and private JSON receipts. Migration 0042 adds an exclusive app-data-relative ModelFile coordinate alongside existing external host paths. Workers stream and hash pinned public weights; the native Runner inspects only fixed immutable references before the existing llama.cpp adapter loads them. Models remain shared infrastructure; download histories remain account scoped.

Reviewed [speech companion bundles](plans/managed-speech-setup.md) reuse that
immutable store and normal worker queue for multiple files. Whole-bundle
publication creates shared ModelFile observations and a private receipt only
after every object verifies. This file-preparation operation does not install
Python dependencies, activate a model definition or claim speech readiness.

The [managed speech environment](plans/managed-speech-setup.md#qualified-managed-speech-flow)
uses the existing runtime-preparation API/supervisor and a fixed typed native
journal. Its normal worker verifies the pinned SDK, dependency, interpreter and
model inputs before offline assembly in an owned memory scope. The guided card
restores private history/progress and supports Stop/Resume. Successful adoption
makes the exact prepared recipe available to ordinary Audio Runs; existing
explicit external speech settings retain priority. Each environment owns its
Python and stdlib independently of application versions. Model files are shared;
preparation receipts, voice recordings and generated speech remain account scoped.

The [managed image profile](plans/managed-image-setup.md#qualified-managed-image-flow)
uses the same runtime-preparation Tasks, verified downloads and native OCI
supervisor for five fixed model companions. Its guided card restores private
history/progress and supports Stop/Resume. Ordinary PhotoExecutor Runs freeze
sources, prompt, seed, resource bundle and deadline; a typed native controller
owns the exact container independently of the Runner process. Missing dispatch
requires a durable Stop fence before reservations are released. Generate, Edit,
one/multiple-reference Recompose, Upscale and restart/Stop passed real separate
API/worker/native qualification with compiled desktop/mobile UI. Existing explicit
photo configuration, including incomplete settings, retains priority. This fixed
Linux NVIDIA profile does not qualify other hardware or consumer installers.

Conversation film sound reuses the [synchronized-sound graph](plans/synchronized-sound.md#conversation-delivery): an owned existing-film selection or an explicitly
requested new Wan film feeds ordinary effects and preview/timeline Runs. A small
container coordinator waits for the verified final film before publishing sound;
no second native API or execution engine is added. The original film, WAV and
saved editable mix retain their ownership and immutable source lineage.

The [next-release contract](plans/next-release-0.1.md), owner direction
2026-10-29, plans private accounts and shared machine resources, persistent
creative sessions, local prompt/search preparation, expressive sound/editing and
guided cross-platform installation. It preserves the existing execution engine.

The optional [MMAudio effects adapter](plans/synchronized-sound.md) uses ordinary
audio.effects Runs and a separate owned CPU preview Run. It freezes an owned
video's timing/content and the pinned runtime observation, reserves one GPU and
load RAM, and publishes a separate WAV plus a source-linked film preview. A fixed
native wrapper samples the complete frame timeline into overlapping eight-second
contexts; exact absolute sample endpoints prevent cumulative drift. Audio's saved
Sound effects workspace reuses private creative history through preserving
migration 0040. It does not introduce another execution engine.

The [account services](accounts.md), qualified and deployed after PR #512, provide
private ownership, username/password/device sessions, optional TOTP, administrator
management/inspection and owner-bound workers and browser state. Shared physical
models/resources do not share user content. `AI_STATION_ACCESS_PROFILE=accounts`
is explicit and cannot revert to operator access after activation.

The creative-workspace candidate adds owner-scoped sessions and append-only turns
through migration 0039. One atomic submission uses the existing typed generator
builder, ordinary Task/Run and an idempotent receipt; no new executor is introduced.
Its generation/draft/history API and five workspace UIs reuse the existing typed
generators, including full-film and whole-recording MediaJobs. Drafts, variations,
Task-wide Stop and explicit administrator inspection share the existing private
account boundaries. See [workspace contracts](creative-workspaces.md). Production
rollout remains separate from qualification.

The [structural edit selector](plans/structural-image-edits.md) is an opt-in typed
model resolution before ordinary image enqueue. A read-only owner-scoped preview
uses bounded deterministic intent and personal defaults; no inference or native
I/O runs there. The selected checkpoint/profile and reason are frozen with the
Run. Retry never re-routes old work, explicit models remain authoritative, and
legacy request serialization is unchanged when Auto is absent.

Optional [speech delivery controls](plans/expressive-speech.md) use the inspected
configured CLI's existing expression, guidance and sampling arguments. A worker
freezes the supported CLI hash; native dispatch rechecks it and passes the same
bounded values to every chunk. Standard speech retains its original identity.

The optional Fish S2 Pro adapter uses the same speech pipeline, with an ordinary
offline transcription prerequisite for a voice reference. A checked same-owner
transcript may be reused; requested TTS words are never treated as recognized
speech. The frozen source/weight/wrapper observation, direction and pace follow
each Run. The worker reserves two compatible GPUs and load RAM; a fixed native
child owns the zero-swap scope, complete EOS-checked chunks and final WAV.
Audio and reviewed media agents share model/direction controls and private
creative history. No model service, new execution engine or schema is introduced.

The [optional prompt enhancement](plans/local-prompt-enhancement.md) extends the
existing local translation preparation/apply executors. Fixed generator/operation
templates, original/effective receipts, same-owner source bindings and normal
dependencies cover images, Wan, ACE-Step and Echo motion prompts. Deferred speech
and agent sources are frozen before preparation; narration/lyrics remain exact.
No additional execution engine, permission, native endpoint or migration is added.

The [common generation-progress implementation](plans/generation-progress.md) projects
measured sampler/chunk observations and owner-scoped comparable-job timing through
the existing Run DTO and MediaJob views. Counters cannot publish artifacts or
change execution state. Queue, preparation, generation and final checks remain
distinct; no new executor, permission or schema is introduced.

The [whole-recording avatar plan](plans/whole-recording-avatars.md) evaluates a
stable global-generation profile after the owner-reported Echo eye deformation.
The optional configured Sonic adapter uses one version-two media plan and one
whole-recording Run, with optional preceding speech preparation. It shares owned
process inspection, resource admission, cancellation, leases and explicit resume
with other workloads. The UI and reviewed agents freeze its recipe and sources;
progress reports real global diffusion windows. It stays disabled by default.
Production defaults and full-resolution long-recording qualification remain
separate rollout gates; a native experiment does not establish quality.

The [Echo portrait continuation candidate](plans/echo-continuation-quality.md)
freezes an appearance recipe and source/model observation in new full-avatar
plans and agent workflow snapshots. Old plans retain legacy behavior; a resumed
job never follows a new recommendation. The private typed Runner verifies the
observation before dispatch and model import. Qualification and rollout remain
separate gates.

[Complete long speech](plans/complete-long-speech.md) keeps bounded text chunks
inside one owned Chatterbox Run. A fixed native wrapper calls the configured
offline CLI sequentially and publishes only the complete PCM output; the original
installed runtime/script and short-text dispatch remain unchanged.

The [fixed Wan APG candidate](plans/wan-continuation-quality.md) binds a built-in
guidance recipe and installed-source observation to new continuation plans.
Native execution rechecks the snapshot; legacy plans retain their identities.
No caller-supplied node, graph, command or model path is introduced. Full-film
qualification and rollout remain separate gates.

Current conversation contract: one assistant interface, with no Chat/Work
selector or replacement execution-mode choice. The orchestrator routes each
prompt to a direct response, permitted tools or an applicable workflow. Routing
never grants permissions; sensitive actions retain their existing approvals.
Specialist workspaces remain available. This decision overrides older two-mode
descriptions below. See the [single-assistant plan](plans/unified-assistant-chat.md).

The [Wan continuation candidate](plans/wan-continuation-quality.md) freezes a
capability-selected conditioning strategy with each new video plan and its Runs.
Last-frame anchoring uses the existing owned clip, private typed Runner and
exact-duration composition. Legacy plans retain their original conditioning on
resume; historical records are not rewritten. Qualification and rollout remain
separate from implementation.

Data-agent notification criteria run as a separate durable, source-bound child after the verified Python result. Model/check failures leave analysis successful and never replay Python. Existing ordinary report checks retain their inline lifecycle. [Contracts](plans/data-result-alerts.md).

Ordinary research reports may carry a reviewed success criterion. A tools-free,
source-bound local check runs within the original report Run/deadline, comparing
the previous verified report with identical settings. Suppression retains the
report and gates both notices and separately reviewed email. Empty policy defaults
retain existing identities. [Contract and acceptance](plans/agent-report-alerts.md).

In Work, default Web availability no longer consumes action routing. Known
non-research actions omit that preference before enqueue; ambiguous instructions
use the existing selected-model planner. Explicit queries/rendering retain their
scope checks. Planner history uses plain saved user text, excluding expanded
attachments. [Routing contract](plans/work-default-web-routing.md).

Settings → Access → **Access from anywhere** provides explicit private-access
installation, Tailscale sign-in/HTTPS approval, an exact private address and owned
Disable. It uses ordinary Tasks/Runs and an isolated native userspace service;
account keys stay outside Docker and agent filesystem roots. Local qualification
is complete; actual account enrollment and phone-outside-LAN acceptance remain
operator steps. [Setup and evidence](plans/private-tailnet-access.md).

A completed analysis can expose **Use result file** and explicit follow-ups such
as “Sort this result file”. These use the complete inspected CSV/XLSX output;
ordinary input-file references retain their original source. See
[result continuation contracts](plans/data-result-file-continuations.md).

Natural data-file follow-ups can reuse the exact inspected files or offline
captures of a completed conversation-linked data agent. The new task has its own
workspace and budget; the agent is not rerun. See
[agent data continuations](plans/conversation-agent-data-actions.md).

Explicit image follow-ups can select a completed linked agent image. The source
is checked on Send and through the existing frozen-input dispatch guard; unfinished
or ambiguous results do not fall back to an older image.
[Agent image actions](plans/conversation-agent-image-actions.md).

Conversation follow-ups reuse saved data answers and coding reviews with verified
source bytes. Media references describe published metadata and explicitly do not
claim content inspection. No new execution or tools are granted.
[Result families](plans/conversation-agent-result-families.md).

Agent execution status follows actual generation stages, with email approval and
transport shown separately. Graph publication alone is not a successful result;
verified bounded repairs preserve their history. [Outcome contracts](plans/agent-workflow-outcomes.md).

Conversation **Run now** buttons queue a durable, exact-card agent action and
retain its execution in chat history. The pending composer and saved Chat mode
remain intact; retries reuse the receipt. Stop follows only the verified owned
background workflow. [Conversation buttons](plans/conversation-agent-run-button.md).

Follow-up Chat/Work replies can quote a completed conversation-linked agent
report with verified bytes, bounded context and visible source provenance.
Unfinished or unavailable reports are identified explicitly; reading a result
does not start another agent or grant tools.
See [agent report context](plans/conversation-agent-results.md).

Work can operate the last agent created in the conversation: **Run this agent**,
**Pause this agent** (future runs) and **Stop this agent** (current execution).
Existing review/enable, approvals, permissions and Task-wide Stop remain in force.
The background execution does not block further conversation.
See [conversation agent controls](plans/conversation-agent-control.md).

Saved HTTP connections can be explicitly attached to agents as **Connected API**.
The saved target revision, server-only credentials, bounded capture and normal
Stop/permission contracts reuse the existing worker. Local Python receives only
verified captured data. See [saved API sources](plans/agent-http-connectors.md).

[Agent result email](plans/agent-report-email.md) publishes a distinct ordinary
email.send child from a verified final agent result. It reuses SMTP connectors,
EmailDelivery, Task serialization and approvals; generation and delivery have
separate outcomes. Optional JSON policy preserves legacy definition identities
and does not add a schema column or a native execution boundary.

[Optional bounded avatar loading](plans/echo-memory-loading.md) reuses the
existing native ProcessManager, fixed private 11-GiB/zero-swap scope and ordinary
media Task graph. Complete existing weights retain full precision; no upstream
files or public command/memory controls are added. Default native arguments are unchanged; new Standard jobs reserve the observed
loader requirement before launch.

> Optional profile: [fixed Wan memory profiles](plans/wan-memory-profile.md) reuse the same native process manager, worker reservations and motion artifacts. The optional profile is disabled by default and requires local qualification; no new execution service is introduced.

[One bounded local-agent correction](plans/agent-validation-repair.md) reuses
the existing validation-repair engine when saved automatic project checks are
enabled. The original deadline, commands, source scope and failed history remain.

[Reviewed research before local agent code](plans/agent-research-coding.md)
reuses the existing source-bound context handoff, public tools and isolated
workspace. One reviewed definition and deadline bind every child.

[Persistent scene-video output](plans/agent-motion-generation.md) reuses the
existing long-media planner, segments and CPU composition on the agent Task.
Reviewed sources and one absolute deadline cover every stage. Only the final
verified film produces the ready notice.
[Whole-avatar agent output](plans/agent-motion-generation.md) additionally reuses
the existing speech/planner/window pipeline with reviewed portrait/audio sources.
Generated speech is bound to its actual owned Artifact before animation. No
additional agent execution engine or model download is introduced.

# Architecture

Entry-point revision (2026-10-25): one assistant conversation replaces
the user-facing Chat/Work switch. The orchestrator selects direct response or
existing capabilities while scoped permissions and approvals remain explicit.
Legacy history/API compatibility stays intact. [Plan](plans/unified-assistant-chat.md).

Video/music translation reuses the image preparation/apply executors and existing
local runtime lifecycle. Same-Task identical film prompts share preparation;
all preparations and reviews gate all segments. Ordinary Resume retains verified
effective text; explicit retranslation uses the frozen earlier policy.
[Contracts and qualification](plans/media-language-workflows.md).

Optional image prompt translation gates an ordinary media Run on local
preparation and optional reviewed-apply children. Shared model startup/eviction,
Run dependencies, approvals and verified Artifacts preserve the existing worker
and native boundaries. [Implementation and qualification](plans/media-prompt-translation-implementation.md).

Composer dictation reuses native CPU transcription and normal Library artifacts.
Direct submissions can carry an idempotent Task receipt; recording inserts only
editable draft text and never executes a conversation turn.
[Contracts](plans/prompt-translation-and-dictation.md#dictation-implementation-contract).

Managed semantic memory uses the existing container executor, not a new service.
A fixed ONNX CPU child owns one ordinary Run; app-owned pinned files, explicit
preparation consent, revision/content guards and parent-death/Stop contracts keep
inference offline and independent of native GPU models.
[Lifecycle](plans/memory-embeddings-readiness.md).

Permanent Library deletion uses an explicitly approved container-side
`artifact_purge` Run. It removes only app-owned bytes and preserves provenance
tombstones; native Host Runner authority is not expanded. The exact selection,
progress and recovery policy are documented in the
[Library deletion contract](plans/library-permanent-deletion.md).

The [Krea 2 image backend plan](plans/krea2-lustify-images.md) extends existing
host-media execution and the model registry. Pinned native runtime code stays
outside control-plane data mounts; fixed per-Run graphs preserve typed access,
resource ownership and artifact lineage. Per-operation model defaults and frozen
checkpoint snapshots reuse ModelDefinition/Settings and the existing photo/media
executor. Real GPU qualification is recorded in the plan; release gates and preview
deployment are tracked separately.

Instruction-only Edit/Recompose reuses the fixed native photo wrapper and the
existing Task/Run lifecycle. Profile names are typed; only constants in the owned
pipeline import change. No external script/model modifications or new execution
boundary. [Contracts](image-workflows.md#instruction-only-editing).

Generated data email attachments reuse the existing final-result/email Run graph,
approval hash and conservative SMTP journal. Frozen selected formats require actual
verified exports; original uploads and scripts are excluded. Empty selections
preserve legacy identity. See [data attachments](plans/agent-data-email-attachments.md).

Conversation file creation freezes bounded earlier plain text on the current
message and Run. Source ownership/hashes gate execution; quoted text grants no
tools, attachment reads or networking. See [creation context](plans/file-creation-conversation-context.md).

Explicit file creation reuses the existing local Python/data graph with zero
input files. Its frozen operation and ordinary output inspection bind later reuse.
See [local file creation](plans/local-file-creation.md).

Conversation Data analysis can explicitly select rendered public URLs. The same
Browser/source/Python graph runs without a persistent Agent, on the existing
conversation Task. See [direct rendered data](plans/conversation-rendered-data.md).

Rendered research reuses the native Browser Run before the existing local-agent
context handoff and isolated code/Python chain. No additional execution engine.
See [rendered research](plans/agent-rendered-research.md).

[Dependency-bound model restoration](plans/dependent-consumer-eviction.md) uses
an ordinary database-only preparation Run. Existing dependencies gate future
consumers across owned stop, media and normal model load, preserving the current
worker/Runner boundary and atomic claim semantics.

[Approved optional Python outputs](plans/python-optional-outputs.md) extend the
existing typed request with a frozen allowlist. Required files remain mandatory;
only present approved extras pass through the owned report and existing export
validation. Native/image feature negotiation and legacy request identity are
preserved. There is no new executor, permission or schema migration.

[Generated analysis files](plans/data-output-files.md) extend the existing
Python request's fixed expected-output list. The model declares only supported
optional names; controller and worker bind the declaration to its source Run.
The result worker checks all exports before creating usable Artifacts. No new
executor, filesystem grant or database schema is introduced.

Image follow-ups also resolve the exact uploaded input of a completed local Vision
inspection. Portable source snapshots bind the user message, orchestration, Vision
child and description artifact; source bytes are checked before reuse. The existing
media children execute the next command. See [image conversations](plans/conversation-images.md).

[Ordinary image attachments](plans/conversation-images.md) reuse stored image IDs,
local Vision and the existing PhotoPipe reference operations. Chat's image-to-Vision
fallback skips unused text-provider/model preparation; Work can retain its normal
selected-model planner. A shared conversation upload mutation preserves partial
batch success and errors across data/image control changes. No new execution engine.

[Conversation CSV/Excel analysis](plans/conversation-data.md) composes the existing
project factory, data workflow, local code generation and offline Python executor
on one conversation Task. A pure definition configures the shared pipeline without
creating a persistent Agent. Frozen user/file scope, private workspace ownership
and one absolute deadline bind every child. The results projection retains
verified repair history without exposing the internal project as a Coding action.

[Spoken agent output](plans/agent-speech-generation.md) reuses the existing
Chatterbox executor and reviewed Library voice references.
Shared scopes, prepared text and owned deadlines use the same media-agent chain;
editor and execution contracts are deployed and real goal-based Polish speech
is qualified; see the linked evidence.

[Persistent media agents](plans/agent-media-generation.md) compose reviewed research,
bounded creative preparation and existing image/music children on one Task.
Fixed descriptions skip text inference. Saved scopes, source hashes and native
owned deadlines remain inspectable; natural drafts stay disabled for review.
Release qualification is tracked separately in that plan.

[Local music](plans/local-music-generation.md) is being added through the shared
media Run/Host Runner boundary. A pinned, explicit model installer is separate
from inference; installing its weights alone does not enable the capability.
[Conversation dispatch](plans/conversational-music.md) reuses that same media
child on a Chat/Work Task without text inference or a second execution engine.

[Research source reading](agent-search-pages.md) composes existing public-search
and HTTP GET steps with a source-bound optional agent tool. The worker verifies
the same-workflow search artifact before selecting at most three public targets;
reporting, deadlines, Stop and artifacts reuse existing infrastructure.

[AI-assisted agent drafting](plans/assisted-agent-drafts.md) uses one local
preparation executor from Agents and as a Work child Run. The HTTP API only
enqueues; model admission, leases, Stop and artifacts reuse existing services.
A validated definition, its JSON artifact and terminal Run publish atomically,
always disabled. Existing quick drafting remains explicit and compatible.

[One-send visual website questions](plans/chat-website-design.md) compose a single
current user URL/design request and Web selection with the existing Browser and
local Vision actions. The advanced rendering option is unnecessary for this route.
Exact search queries and text-only overrides retain their authority. Page content,
quotes and Web alone without a visual request cannot grant Browser or model
management. The capture is bound to its successful orchestration origin before
pixel analysis. No initial text-model inference, new executor or network grant to
Vision is added.

[Rendered page reading in Chat](plans/chat-page-reading.md) composes the existing
native Browser child and queued Chat completion through RunDependency on one
Task. URL scope is an explicit one-turn Web option; source JSON/screenshots,
hash-checked follow-ups and targeted Stop reuse existing ownership and artifacts.
The text reader receives captured text. [Explicit screenshot design analysis](plans/page-screenshot-vision.md)
composes the existing local Vision action with a verified saved capture. Its
Markdown artifact binds the selected PNG and page JSON; follow-ups can reuse the
attributed pixel observation without a new browser or inference engine.

[Natural image continuations](plans/conversational-graphics.md) reuse verified
page observations in the existing image-brief/photo chain. Image references and
selected media actions treat ordinary Web as availability, while exact research
scope remains explicit. Request receipts and conversation preferences are preserved;
there is no new executor, schema or execution boundary.

[Deterministic price observations](agent-market-watch.md) and scoped SMTP alert
delivery are deployed (#340, #342, #343). Fixed public source reads, comparisons,
in-app notices, reports and mail use existing Tasks, workers, child Runs and
Artifacts. Explicit activation grants bind automatic mail; Task-wide Stop covers
all published submissions. There is no model-based pricing or new execution
service. [Stock data](plans/stock-price-agents.md) is an optional account-based
integration deployed in #344; no real account read has been verified. Ordinary
stock-research requests instead draft existing public search/page tools with the
selected local model. A saved public query or URL is reviewed before activation;
the full private goal is never automatically submitted to a search engine.

[Reviewed agent build preferences](agent-website-build-policy.md) extend the
existing owned-workspace setup with frozen dependency/check automation. The flags
apply only when creating a private Local agent project; an existing linked
project's saved policy remains authoritative. They add no execution boundary.

[Offline website preview](agent-site-preview.md) runs frozen successful static
builds in a CPU-only, network-disabled native-owned Chromium container. It uses
separate inspection Tasks and child action Runs, immutable PNG artifacts and
confirmed cleanup before releasing resource holds. The UI never executes generated
site JavaScript in the authenticated control-plane origin. Release qualification
is recorded separately from implementation.

Agent details separate a results-first [workspace](agent-workspace.md) from saved settings. Run now keeps progress and results on the agent; code-capable agents reuse the existing Task conversation for inline review and follow-ups. Legacy task URLs remain available.

[Isolated Python execution](agent-python-execution.md) adds a typed, explicitly
permissioned container executor behind the native Runner. It snapshots approved
worktree code and input artifacts, uses no host-writable mounts or networking,
and returns bounded verified output artifacts. Agent workflow/UI wiring remains
separate acceptance; this executor alone does not enable spreadsheet agents.

## Current product priority — agent-first

The user's [2026-10-15 decision](plans/agent-first-product.md) makes persistent
agents with local code execution the priority. Coding/Git/worktree services remain
shared infrastructure; a standalone IDE-like workspace and expanded external coding
CLI integrations are deferred. Next: isolated Python/data processing, agent results
and website-building UX, then typed price observations and scoped email delivery.
This is a priority change, not a claim that these workflows already work.

[Component validation environments](self-development-validation.md) extend the
existing frozen project preparation/dependency/check chain with development locks,
a nested Node component, owned Python source roots and bounded check deadlines.
No new host access or independent execution architecture is introduced.

[Reviewed-page coding](agent-page-coding.md) composes existing public HTTP context
Runs with Local Coding. A dependency-gated metadata stage verifies immutable
source artifacts and publishes the normal coding chain on the same Task, with a
shared deadline and existing approval, Stop and conservative recovery contracts.

## Planned conversation and long-media milestone — 2026-10-14

The [first-send increment](first-send.md) now adds transactional turn receipts and
mode enforcement to existing services, with no additional execution architecture.

[Create project & build](assistant-project-build.md) composes existing setup,
worktree, proposal and configured checks on the same Task. Only confirmed setup
completion publishes coding; failure preserves the created project and the failed
stage. The dispatcher performs deterministic routing without provider inference.

[First-use model loading](chat-model-selection.md) uses the existing owned runtime
load prerequisite. Merely selecting a GGUF creates no workload; explicit presets
or dynamically discovered devices configure its first consumer.

The [implementation brief](plans/2026-10-chat-work-media.md) and
[updated handoff](plans/implementation-handoff.md) distinguish delivered and planned
increments. Atomic first Send, server-enforced Chat/Work, selection-only local
autoload, the [shared conversation shell](conversation-shell.md), the
[unified model catalog](model-catalog.md) and distinct System/Settings are delivered.
[Qualified thinking](chat-thinking.md), session drafts and searchable history are also delivered.
[Automatic local coding routing](coding-auto-model.md) uses installed GGUF/context
observations and worker-owned runtime preparation. Auto requires 100k+ actual
context at coding dispatch, records the chosen model and never grants external AI.

[Contextual Work](contextual-work.md) reuses coding Tasks/worktrees with durable
Task Stop. [Long-media jobs](long-media.md) add durable segmented video/full-speech
avatar plans, existing RunDependency edges, owned native execution and a typed CPU
composition executor. Final job success requires a verified final artifact from
the selected revision. Task Stop/resume covers this bounded graph; resource
admission includes GPU and host RAM. Longer output hardware qualification is
recorded separately from normal fake-GPU/real-CPU integration tests. See
[the media execution design](plans/long-media-execution.md) for subsequent profiles.

[Explicit video scenes](video-storyboard.md) partition the same independent-shot
graph at scene boundaries. Per-stage prompts and scene identity, deterministic
seeds, ordered composition/lineage and existing Stop/resume/resource admission
stay within the media capability; the native API and database schema are unchanged.

[Named-project Work](named-project-work.md) resolves an explicit current-turn
project change instruction into the existing typed Local Coding Auto scope.
It freezes project identity/revision before enqueue, preserves explicit task
selection and receipt replay, and performs no model inference to select a project.

[Conversational media](conversational-media.md) exposes the same aggregate jobs
in Chat/Work, with final-only artifact projection and task-wide Stop. Deterministic
video/avatar actions do not require an LLM planner.

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage, including bounded text, PDF text extraction and stored image attachments and assistant pixel inspection through owned vision GGUF/projector pairs, plus a persisted provider registry with secret references. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation, explicit confirmed removal are enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents now have reviewed definitions, explicit activation, durable schedules, scoped context tools, GET of reviewed public pages, versioned Skills as instruction packs, optional durable approval before each Run, sequential or gated workflow steps, optional bounded registry tool calling during the report, saved retry policies and in-app notices. Named HTTP GET connectors with secret references are inspectable health Runs; public-page Browser is an optional agent workflow tool; account browser automation and other connector kinds stay unpublished. Bounded Cursor and Local AI file-edit proposals (complete rewrites or unique snippet replacements), review artifacts and separate validation Runs are operational. Declared Python dependency installation in owned worktrees is operational. Codex also uses the bounded proposal workflow; Claude Code remains inactive. The Platform assistant can review, commit and publish those coding Tasks through the same Git domain services, and can load or unload owned llama.cpp instances without granting extra permissions from a model plan. See README for runnable commands and limitations.


AI Station is a local-first AI workstation control plane. It is a modular monolith with one deliberate process boundary: a Dockerized control plane and a native Host Runner.

```text
User
  │
  ▼
Web UI ── HTTP/SSE ── FastAPI control plane
                         │  tasks, runs, events, artifacts
                         │  worker + scheduler
                         │  SQLite (WAL) under app data
                         ▼
                    Unix socket
                         │
                         ▼
                   Host Runner (typed API)
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
        Git/worktrees  photo_pipe   telemetry
        Codex/Cursor   processes    discovery
        Claude Code
```

Future remote machines register as additional runners. Capability code depends on an execution target, not on "this host".

## Processes

| Process | Where | Role |
| --- | --- | --- |
| `ai-station` | container | HTTP API, UI, SSE |
| `worker` | container | claims runs, dispatches executors |
| `scheduler` | container | creates runs from schedules; samples telemetry |
| Host Runner | host user session | typed host operations |

The three containers share one image and different commands. They do not receive `--privileged`, the Docker socket, or unrestricted host mounts.

## Persistence

Application data lives in one directory (`AI_STATION_DATA_HOST_PATH` on the host, `/data` in containers). The database stores AI Station-owned files as paths relative to that root (`artifacts/ab/cd/<uuid>.png`). External models and repositories are references, not copies.

Replacing containers does not drop the database, artifacts, memory, or run history because those files are on the host bind mount. The launcher's `compose down` never passes `--volumes`. `/data` is not a named volume.

## Execution

Coding providers share the [selected source removal](coding-file-removal.md)
contract alongside checked writes and snippet replacements. Removed paths retain
source hashes and reversible diff artifacts; follow-ups and reviewed commits use
the same task/worktree boundary.

Almost every action is a **Task** that produces one or more **Runs**. A Run is performed by an **Executor** on an **Execution Target** (`host` or `container`; `remote-node` is reserved). The worker is the only component that executes runs. HTTP handlers enqueue work and stream stored events.

The worker container supervises bounded independent process slots (three by
default, configurable with `AI_STATION_WORKER_SLOTS`). Slots share the durable
queue and resource reservations, not ORM sessions or executor instances. They
preserve the same claim, permission, cancellation and recovery contracts. See
[execution model](execution-model.md) for shutdown and restart behavior.

The Host Runner does not expose an arbitrary shell. Photo, Git, coding CLIs, cancellation, telemetry, and discovery are separate validated operations.

The launcher verifies the Runner's startup-captured native source identity before
reusing it. A healthy process with different or legacy source cannot silently
serve a newer control plane. See [local compatibility](runner-source-compatibility.md).

SQLite backups are explicit Task/Run copies (`VACUUM INTO` plus integrity check). A successful copy can be re-checked in place. The Host Runner can inspect `ai-station:local` versus running compose containers without building or retagging; restore and image rollout stay unpublished. See [operations](operations.md).

## Networking

Synchronous operator-session database checks run in the thread pool. SQLite lock waits must not block the HTTP event loop: response completion releases other request sessions, so blocking that loop can turn ordinary concurrent reads into database-lock failures.

The published UI/API port is `127.0.0.1:8765`. Inside the container the process listens on `0.0.0.0` so Docker's localhost publish mapping works. That internal bind is not host exposure. `AI_STATION_BIND_HOST` is the host publish policy; a non-loopback value aborts startup. An optional operator password can be stored as a PBKDF2 hash and then gates the loopback UI with a session cookie that idles out after 30 minutes and cannot outlive 12 hours. Optional private UI access uses an additional explicit IPv4 publish address and requires the stored operator password; it does not expose native Runner or model ports. See [private network access](private-network-access.md). See [nodes and operator access](nodes.md).

Loopback-only host model services are reached through the private Host Runner bridge. Optional direct container connections use `host.docker.internal` or another configured reachable endpoint; container `127.0.0.1` remains the container itself. The only networked node is this Host Runner over its Unix socket. Remote invitations and loopback token registration persist as `StationNode` rows; they do not add a LAN listener.

## Extension points

New behavior plugs in at:

- executor (`Executor` protocol)
- LLM provider (OpenAI-compatible client)
- tool (registry entry with permissions and a real implementation)
- connector (status and credential reference; no fake integrations)
- runtime / model discovery (host scan, no mutation) and explicit local installation (verify existing files/images, never pull)
- skill (versioned directory under `skills/`)

## Scoped memory integration

Agents may explicitly select `project_memory`, which grants only `project_memory_read` on their snapshotted linked project. Retrieval is an ordinary child Run with saved context and provenance. Linking a project alone grants no memory or repository access. See [memory](memory.md#explicit-project-memory).

The [Memory workspace](memory.md) exposes durable scoped entries with validated provenance and FTS retrieval. Optional embeddings use an explicit local OpenAI-compatible endpoint; they are not downloaded and fail closed without that setup. Chat snapshots only enabled pinned global and matching conversation entries into new Run parameters; changes never rewrite historical contexts. The editor reuses the shared list keyboard on pin and enabled flags with unique Memory names; Space or Enter selects the focused row and does not invent a Run.

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred. Users may then save a curated definition with a load preset and explicitly install it; installation verifies the existing file and an already-present llama.cpp image, and never downloads GGUFs or pulls container images.

## Local agents

[Agent lifecycle](agents.md) uses the shared queue, local provider, Run events and Markdown artifacts. Explicit telemetry, own-scope memory, configured public search and GET of reviewed public pages gather bounded context as persisted child Runs before the report. Optional bounded tool calling during the report may request those same selected registry tools; invented tools, URLs and commands fail closed. Versioned [Skills](skills.md) inject reviewed instruction text; they do not grant tools or permissions. The definition editor reuses the shared list keyboard on installed Skills and tools with unique Skill/Tool names; Space or Enter selects the focused row and does not invent a Run. Approval, retry and notice policies reuse that sequence with unique Approval, Retry and Notice names; Space or Enter selects the focused row and does not invent a Run. Bounded tool calling and sequential or gated workflow mode reuse that sequence with unique Tool calling and Workflow names; Space or Enter selects the focused row and does not invent a Run. Linked project radios reuse that sequence with unique Linked project names; Space or Enter selects the focused row and does not invent a Run. Save definition persists it through `PUT /api/agents/{id}`; that tags Runs for filtering and does not grant coding access. The Agents list shows that project name and can filter through `GET /api/agents?project_id=`. Inspect project and View tagged Runs stay on that card and open the project and the tagged Runs filter without calling Enable. View tagged Runs stays on a saved agent even without a project. A saved definition link opens them the same way. The tagged Runs list and Run inspector open that agent and project without calling Enable. The inspector opens tagged Runs from a saved project_id even without an agent, and from a saved agent_id even without a project. Project details list those linked agents from that same query; Enter inspects the selected definition. View tagged Runs stays on that row. Project details also open tagged Runs through `/runs?project_id=`. View all linked agents opens the Agents filter. That list does not grant coding access or Enable or Run now. The Agents definition shows other agents on that same project and omits the current definition. The conversation shows that same list after agent.create. Definitions start disabled; the natural-language factory copies recognized schedules and policies into that disabled draft. Unsupported tools block activation. Enable stays disabled in the conversation and Agents until those tools are removed, a local model is selected, and web_search or http_fetch have their saved query or URLs. The conversation can remove an unavailable or unknown attached tool through `PUT /api/agents/{id}` without calling Enable. Add stays on an operational catalog tool through that same PUT; unpublished adapters cannot be added. The conversation can save the UTC schedule through that same PUT. The conversation can save approval, retry, notice, sequential or gated workflow and bounded tool calling policies through that same PUT. The conversation can save the goal and system prompt through that same PUT. The conversation can save the name, time limit and expected outcome through that same PUT. The conversation can save the description through that same PUT. The conversation can save a linked project through that same PUT; that tags Runs for filtering and does not grant coding access. An optional durable Approval can park the parent workflow before children are published. Gated mode parks the report after those children succeed. The conversation, Agents, Home and the Run inspector grant or deny that parked Run through the existing approval endpoint without starting tools from the UI. Conversation and Agents Stop an in-progress history Run through the existing cancel endpoint without opening the inspector. The latest ordinary agent report is shown inline from its stored markdown artifact. Independently recorded search sources, fetched pages and registry tool calls from that report stay next to it. Workflow steps of the last parent stay next to history from that parent's `workflow.steps`; Enter inspects the child Run. A saved observation opens Memory. The conversation can Inspect this agent's memory. Attached skills are listed from the installed catalog; Review instructions stays on the selected row and does not invent a Skill Run. Remove stays on a stored id missing from that catalog and saves the remaining list through `PUT /api/agents/{id}` without calling Enable. Add stays on an installed catalog skill through that same PUT. At most four. Saved in-app notice policy is shown on that definition. Attached remember-reports or remember-workflow tools show how observations are stored. An enabled idle definition can Run now from the conversation through the existing agent run endpoint without opening the inspector. Saved retry policies never auto-loop; manual retry starts a new Run from the snapshot. Saved notification policies write in-app notices. Scheduling is serialized, persistent and non-overlapping.

## Named connectors

[HTTP GET connectors](connectors.md) persist a reviewed public URL and optional secret reference. A user-requested health check is an ordinary Run with `network_read`, cancellation and a JSON artifact. Public-page Browser is a separately permissioned agent tool; GitHub repository snapshots also support reviewed read-only account access; email, calendar and social adapters remain unavailable.

## Runtime observations

The [external runtime registry](runtimes.md) records bounded native process observations and the configured local endpoint’s model-discovery health through an explicit worker Run. It grants no runtime management capability and preserves earlier observations after errors.

## Host loopback model access

Compose defaults to the [typed local-model bridge](local-model-bridge.md) over the existing private Runner socket. Model listing and bounded streamed completions target only the configured local endpoint, with no redirects or caller-selected URL. Canceling a Run closes the upstream response. Direct provider transport remains available for native development and explicitly configured container-reachable endpoints.


## Dashboard activity projection

The dashboard reads bounded summaries of persisted Runs, enabled agents, upcoming schedules, conversations, generated artifacts and runtime observations through `/api/dashboard`. Those agent summaries include a saved `project_id` when one exists. Home opens that project and the tagged Runs filter without calling Enable. View tagged Runs stays on a saved agent even without a project. The tagged Runs list and Run inspector open that agent and project without calling Enable. The inspector opens tagged Runs from a saved project_id even without an agent, and from a saved agent_id even without a project. Home attention notices include that saved agent and `project_id` and open them the same way. In-progress and waiting agent Runs include those same ids from `/api/dashboard` and open them the same way. In-progress coding and worktree Runs include `project_id` from that payload and open the project and the tagged Runs filter without starting a coding Run. Home unifies interrupted work, notices and in-progress Runs into one attention list. Arrow keys move between attention rows; Enter inspects; Stop, Retry as a new run, Mark inspected, Mark read, Approve and Deny remain on the selected row and include a short Run or notice id. That sequence reuses the shared list keyboard. Those actions call the existing cancel, image-retry, workflow-retry, interrupted-acknowledgement, notice-read and approval endpoints. Image retry stays on Home and does not open the inspector; Mark inspected still does not replay. A failed agent notice can Retry as a new workflow when `retry.allowed` is set; that does not call Run now. Audio and avatar retries stay unpublished. Granting a parked Run queues it for the worker and does not start tools or inference from Home. They do not restore backups or start discovery. Upcoming schedules, enabled agents, recent conversations, recent artifacts and runtime observations each reuse that list keyboard with unique Inspect names; runtime rows open System rather than inventing an observation Run. Activity sections, compute telemetry and the resource chart are labelled landmarks. Home GPU cards reuse the shared list keyboard with unique GPU names; live telemetry stays on Home and there is no inspectable GPU Run. Home CPU, memory, storage and in-progress Run cards reuse that sequence with unique Metric names; Enter inspects Runs from that card and does not invent a telemetry Run. GPU allocation checkboxes in Chat, Models and the assistant load form reuse that sequence with unique Allocate GPU names; Space or Enter selects the focused card and does not invent a Run. Explicit Coding file checkboxes reuse that sequence with unique Edit file names; Space or Enter removes the focused path and does not start a coding Run. Runtime observations retain their original age and source; overdue schedules remain visible without promising an execution time. Hardware and worker/scheduler health retain their separate live endpoints. Status also lists held run leases and expired-lease counts without recovering or replaying them. Ctrl+K opens the command palette, including Backup and upgrade readiness. After in-app navigation the workspace `#main` region is focused, the document title matches the destination, and a polite live region announces that workspace. Overlay pickers keep Radix titles, descriptions and focus traps. Command palette, Library, model and media search fields have accessible names. Sidebar chrome and placeholders use AA contrast tokens. The Runs table uses the same arrow-key selection; Enter inspects the selected row. Remaining keyboard workflows stay open.


Conversation summaries use a dedicated persisted coverage/provenance record and the existing scoped Memory model. [Summary updates](conversation-summaries.md) run through the worker and preserve the full conversation history.


Saved project test/lint/build commands now run through the worker and a managed native sandbox in an owned worktree. Commands are snapshotted from versioned project settings, Git metadata stays read-only, networking is blocked, and results become events plus a JSON artifact. Declared Python dependencies are installed by a separate typed Run that uses vendor wheels offline or a public PyPI index after SSRF-safe DNS checks. See [project validation and dependency installation](coding-boundary.md). The [bounded Cursor adapter](coding-cursor.md) adds explicit external-AI consent, checked selected-file writes, review artifacts and a separate validation Run; other provider adapters remain disabled. Coding, follow-up and assistant consent checkboxes reuse the shared list keyboard with a unique Consent name; Space or Enter selects it and does not start a coding Run.

## Reviewed Git progression

[Reviewed commits](coding-commits.md) extend a completed coding Task with a user-approved Git Run. The review acknowledgement reuses the shared list keyboard with a unique Review name; Space or Enter selects it and does not queue a commit. Approval data binds the exact review and validation snapshot; the native Runner owns checked commit publication and its interruption journal. The [full-product ledger](product-completion.md) tracks the remaining acceptance increments.

## Conversation orchestration

The default entry point is the [platform assistant](orchestrator.md). Dedicated workspaces remain available. Conversation intent is compiled into typed capability actions, dispatched as ordinary Runs, and projected back into the conversation with live state and artifacts. Coding review in that conversation and on the Run inspector lists files as a keyboard listbox that shows only the selected patch, labels cumulative diffs against the task base, lists saved validation commands from that validation Run with unique Command names, and links the stored patch artifact without changing commit or publication permissions. There is no inspectable validation-command child Run. That file list reuses the shared list keyboard; Enter does not open a Run. Repository exploration steps use the same sequence with unique Step names and do not invent an exploration Run. Explicit assistant file checkboxes reuse that sequence with unique Edit file names; Space or Enter removes the focused path and does not enqueue a coding Run. Staged Chat text attachments and assistant image references reuse that list keyboard with unique Attachment and Image reference names; Remove and reorder stay on the selected item and Enter does not send. Saved Chat transcript attachments are a nested sequence with unique Saved attachment names; Enter opens the selected file and does not inspect a Run. Images workspace sources use the same sequence with unique Source names; Enter does not queue a photo Run. The assistant shares domain services with workspaces; it cannot bypass their permissions, resource scheduling or native boundaries.

## Owned llama.cpp instances

[Managed llama.cpp](managed-llama.md) loads discovered GGUF files into an owned container through the native Runner. Inference uses a private Unix socket, selected GPUs remain reserved for the runtime lifetime, and a separate stop Run releases them after confirmed termination. Health inspects only that owned instance; restart reuses the saved load preset after a confirmed stop. The configured Ollama/OpenAI-compatible endpoint remains available alongside it.

## Runtime prerequisites

RunDependency records durable scheduling prerequisites independently of parent Run provenance. The worker skips blocked Runs, fails consumers of unsuccessful prerequisites, and continues unrelated work. Managed model selection and idle eviction compose ordinary load/stop Runs with Chat, agent, summary and image Runs. See [managed llama.cpp](managed-llama.md).

Speech and images share the owned-process media executor lifecycle; capability adapters provide typed dispatch and output validation. See [local speech](audio.md) for the Chatterbox contract.

Portrait animation uses the same owned-process media lifecycle as images and speech. The native EchoMimic adapter runs offline with CPU offload; Video and Avatars expose the real `avatar.animate` capability, and MP4 results retain image/audio lineage. See [avatar execution](avatars.md).

Reviewed Coding commits use `coding.commit` Runs and a typed native job. A private Git index limits the commit to verified review snapshots; compare-and-swap advances only the owned task ref. Worktree manifests retain their original base and current owned HEAD. NativeJobExecutor shares the existing dispatch/poll/cancel lifecycle with Cursor proposals.

[Library management](library.md) separates versioned user annotations and reversible Trash from immutable execution provenance. Run history and source/derived lineage retain access to artifacts in Trash.

[Local coding proposals](local-coding.md) extend the existing owned-worktree proposal and validation flow with local inference through the private Runner bridge. The native snapshot/write boundary and review artifacts are shared across proposal providers.

The central Assistant can route selected-project coding to the conversation's local model through the same local proposal workflow. A coding scope without external consent routes locally; model-generated plans cannot grant Cursor permission. Project/version/file validation remains in the shared coding enqueue boundary. After a proposal in that conversation, the assistant projects the review and can queue `coding.commit` or `coding.publish` through the same domain services; the model cannot confirm review or GitHub approval.

Optional Chat web search is a permissioned worker tool inside the existing Chat Run. It uses a private SearXNG service and stores sources as events/artifacts before passing untrusted snippets to local inference. The switch is off by default; model-generated routing cannot enable it. The composer reuses the shared list keyboard on that toggle with a unique Search name; Space or Enter selects it and does not send. See [web search](web-search.md).

Research agents reuse the same bounded search tool as Chat. An explicit saved query is required before activating web_search, and only that query reaches search engines. Manual and scheduled executions snapshot the query and network permission in ordinary Runs; sources are recorded before local report generation. No browser/page-fetch capability or model-generated network permission is introduced.

Local coding optionally uses a bounded read-only repository exploration loop inside its owned worktree before proposal generation. The local model requests typed listing, literal search, file reads, public GET and optional configured search; public URLs written in the task are fetched first. The Runner validates each request and records observations. Cursor and Codex discovery stay repository-only. Selected snapshots then enter the existing checked-write, validation and review workflow. No arbitrary shell, browser, external model or access to the active checkout is introduced.

Agent report retention is an explicit output tool. Selecting `remember_report` grants only scoped `memory_write`; successful output is stored as an observation with Run provenance. `remember_workflow` stores successful telemetry, public search and HTTP fetch child observations the same way and does not copy `memory_search`. Retention and successful final state share one transaction, while cancellation/failure do not populate memory. Existing scoped retrieval and Memory CRUD remain the inspection and control surface.

Local coding repair is a user-requested child Run after confirmed validation failure. It reuses the owned task worktree, original model/file scope and saved validation commands. Bounded failure observations enter the local prompt as untrusted data. The Runner retains a cumulative review against the task base; superseded proposals cannot be committed. Each repair reruns validation and requires a fresh human review. No cloud execution, automatic retry or command changes are introduced.

Local tasks may opt into at most two automatic repair attempts. The budget radios reuse the shared list keyboard with unique Repair names; Space or Enter selects a row and does not start a coding Run. The budget is snapshotted at task creation; only confirmed validation failures queue the existing local repair operation. Each attempt is a separate Run using the same owned worktree, model, scope and commands. Cancellation, interruption, proposal failure or exhausted budgets stop the chain. Review/commit remain explicit.

Reviewed GitHub publication is a separate user-approved Task/Run operation after a successful reviewed commit. The approval checkbox reuses the shared list keyboard with a unique Publication name; Space or Enter selects it and does not publish. The control plane snapshots project policy, exact commit, origin repository, integration branch and PR text into an approval record. The native Runner revalidates ownership and origin before dispatch, publishes only the owned `ai/` ref, and opens a draft PR. Network Git uses a private bare export with the validated object store and clean configuration, so source repository hooks, credential helpers and URL rewrites are not executed. Existing `gh` authentication is reused without copying credentials. Cancellation or uncertain network completion requires inspection; publication is never blindly retried and never merges.

Automatic conversation memory is a saved opt-in policy, default off. A successful Chat Run may enqueue one existing summary Run in the same transaction, linked to that answer. Summary failure cannot change answer success or previous memory; provenance, cancellation and inspection use the established Run lifecycle.

The Codex proposal adapter reuses selected-file snapshot application, native process ownership, validation and reviewed Git progression. It isolates the provider workspace and permission profile from the task worktree; explicit external consent remains required. See [adapter contract](coding-codex.md).

Coding workspaces make Task the durable user-facing coding conversation. Managed project setup and subsequent turns remain ordinary Runs; the Host Runner owns repository creation and isolated worktrees. See [coding workspace design](coding-workspaces.md).

## Conversation workstation inspection

`system.inspect` is a read-only child Run. The worker invokes the existing typed Runner hardware endpoint, then atomically publishes observed artifacts and an inline conversation report. It needs no LLM or GPU reservation. The planner also receives bounded, immutable same-conversation excerpts without previous permissions or attachment IDs. See [station inspection](station-inspection.md).

## Architecture-aware model context

Owned Q8 llama.cpp load Runs inspect a bounded GGUF header through the typed Runner model-verification operation. The worker records the architecture-derived KV estimate and fitted context before dispatch; handlers do not open external model files. Saved observations are bound to file size and modification time. See [local coding context](model-context.md).

## Local pixel vision

The assistant dispatches image inspection through ordinary owned runtime-load and Chat Runs. Its worker prepares explicit artifact images as bounded inline inputs, and the private Runner rejects remote image URLs. A paired projector is mounted read-only beside the selected model. Descriptions persist as Markdown artifacts with source lineage. See [Chat vision](chat-vision.md).

## Coding agents

Agents may explicitly select the Local coding tool and a Project. They publish the same fresh-worktree/exploration/proposal/validation Runs as manual Coding. The child chain stays inspectable in agent history and Coding; no commit or publication is implied. See [coding agents](agent-coding.md).

Image generation and edits can now queue a dependent 4× Upscale with the existing photo executor. The result/completion and child publication are atomic, and Images follows the active stage after refresh. See [image workflows](image-workflows.md).

Portraits can now use a voice reference and typed Polish speech through a sequential Chatterbox → EchoMimic workflow, retaining both outputs and following the active stage after refresh. See [speaking avatars](speaking-avatars.md).

Public GET adapters pin connections to checked DNS addresses, preserve original HTTP/TLS identity and isolate each redirect connection. Origin changes drop connector credentials. See [network boundaries](security-model.md#public-connection-identity).


Public-page browsing is available as an optional isolated agent workflow tool,
with JavaScript, Library screenshots, bounded text, exact container ownership and
cancellation/recovery. It requires an explicitly built local executor image and
configuration; missing setup remains unavailable. See [browser setup and security](browser.md).


## General video

[Wan video](video.md) reuses HostMediaExecutor and native process ownership. A fixed
worker invokes required built-in ComfyUI components; no ComfyUI server or raw
workflow graph is exposed. Inputs/output/cache and transient configured-model aliases
belong to the Run directory/data root; installed models and runtimes are unchanged.


The Assistant's bounded Image → video workflow composes the existing photo and
Wan executors. Successful image registration, child publication and completion
commit atomically; the child consumes only that registered artifact and uses a
new normal GPU reservation. See [media workflow](image-workflows.md).

Search-informed image generation composes ordinary Assistant → Chat brief →
Photo Runs in one Task. The search switch augments an explicit new-image intent
instead of overriding routing. Sources and the generated prompt are persisted;
only successful bounded inference publishes the photo child in the completion
transaction. See [web search](web-search.md#search-informed-image-generation).

The image Generate adapter's prompt-only profile changes two style defaults in
an owned imported pipeline process without changing the original file. The
configured pipeline and Python remain administrator-owned; callers select only
the typed profile. See [image profiles](image-workflows.md#prompt-only-generation-profile).

Optional research can now precede the same first-frame animation workflow.
The selected action determines whether a bounded Chat brief publishes a plain
image or an image with the user's separate motion instruction; photo completion
then publishes Wan atomically. No model-generated tool graph is executed.

Assistant project creation reuses the existing pure setup enqueue service with
its parent's Task and ordinary native executor. The worker alone creates the
repository/environment. Success publishes the saved project's identity back
to the conversation; continuation selects a versioned coding scope without
starting work from the UI. See [assistant projects](orchestrator.md#create-a-project-in-the-assistant).

System and the central workstation report now include bounded NVIDIA compute
process observations: GPU, executable basename, PID and reported VRAM. They
never expose command lines or control external processes. See
[GPU process reporting](gpu-processes.md).


Chat and Work Stop address the active Task within that conversation, including
project setup before a coding workspace exists. The durable Task stop marker
blocks later child publication; a stale stop targets the original Task, never a
new turn. A pending owned llama.cpp load is retained if another active Task
already depends on it. The stopped conversation's consumers are canceled while
the other conversation keeps its model prerequisite. Newly submitted consumers
cannot attach to a startup already being canceled. Native cancellation and
process inspection continue through the existing worker/Runner contracts.

Work can explicitly bind a conversation to an existing owned coding Task through
`ChatWorkContext`. This selection is metadata only and version-checked; it never
moves the Task's original conversation/history, grants external-provider consent,
or launches work. Follow-up Runs retain the same Task/worktree and record the
conversation that submitted that turn. Existing conversations without an explicit
binding retain their original automatic task context.

A Coding session can stage its existing Task in the blank Work composer. The
read-only draft context and pinned proposal version do not create database rows.
First Send atomically binds the new conversation to that Task, enqueues its
follow-up and records the existing chat turn receipt. Invalid scope/consent or a
stale proposal rolls back the conversation and binding. Conversation model
settings never replace the selected task's executor/model.

Full-recording EchoMimic jobs can carry bounded, model-observed safetensors motion
checkpoints as hidden general document Artifacts. Their in-process adapter preserves
the existing portrait identity reference and shared seventeen-frame prefix through
flow-scheduler steps. Installed models/runtime source are unchanged. Legacy clips
without checkpoints use the existing pixel path. See [Echo motion](echo-motion-context.md).

GitHub repository snapshots use the same [connector registry](connectors.md) and
ordinary native Run contract. Only fixed GET projections run through the existing
host gh session; connector metadata and snapshots never expose credential values.

Local agent workflows can now gather [reviewed GitHub snapshots](agent-github-reports.md) through the same native connector executor. The agent stores a resource identity, receives minimum child permissions, and passes only a bounded excerpt to its local report model. No extra execution engine or account-write integration is introduced.

## Offline transcription

[Audio transcription](audio-transcription.md) adds a CPU-only typed native executor
and conversation action using the shared Task/Run infrastructure. Audio remains
inside application storage; model files remain external references. Whisper's
optional Python environment does not change the control-plane image or existing
speech/video runtimes. Immutable source/model checks, bounded offline audio decoding and
verified completion gate TXT/SRT/JSON artifact publication.

[Transcript conversation continuity](transcript-conversation-context.md) adds bounded, source-checked artifact references to the existing Chat, planner and summary snapshots. It grants no new tools or host access and preserves original message coverage offsets.

[Recording questions](conversational-audio-analysis.md) publish an ordinary Chat child only after verified native CPU transcription. Both stages share the original Task, frozen provider/model selection and task-wide Stop; publication is transactional and idempotent. No additional execution engine or schema is introduced.

[Chat recording](chat-recording.md) is browser-side capture and an ordinary artifact upload; no workload executes until Send. It reuses the existing typed local transcription and Chat graph, without another executor or database migration.

[Conversation archive](conversation-archive.md) adds a reversible metadata lifecycle with migration 0024. Archived history remains inspectable, while idle/version guards prevent new execution until restoration. Related Tasks, Runs, artifacts and memory retain their original ownership.

[Agent coding providers](agent-coding-providers.md) reuse the same worktree/proposal/validation chain for explicitly selected Local AI, Codex and Cursor tools. A frozen exclusive tool and permission profile bind the parent to one provider; no external fallback or separate coding executor architecture is added.

[Auto Local Coding agents](agent-coding-auto.md) reuse the existing observed-fit/context router. Drafts and definition edits are metadata-only; enable/launch check candidate fit and post-approval coding dispatch records the actual local model. No separate inference engine or silent small-model/external fallback is introduced.


## Node project dependency execution

The existing project dependency executor also handles Node-only worktrees through
the native runner. A checked npm v3 lockfile pins canonical public-registry tarballs
and SHA-512 integrity. Runtime selection is host configuration; HTTP cannot supply
commands or runtime paths. Lifecycle scripts are disabled during installation.
Saved build/test argv use the same configured runtime with network access disabled.
See [Node project dependencies](node-project-dependencies.md).

Missing npm lockfiles are resolved in an owned staging directory by a network-disabled
npm process. A typed public-registry metadata client primes its bounded cache;
only checked source/integrity records enter it. Complete optional dependency
coverage and final lock validation gate exclusive worktree publication and npm ci.
There is no caller-selected registry URL or additional execution architecture.


## Automatic coding project preparation

Explicit persisted project policies are snapshotted on Send and agent launch.
The ordinary coding Task adds a read-only project-plan Run, serial typed
Python/Node dependency Runs and dependency-gated isolated validation. Manifest
hashes and source ownership bind the graph; manually configured argv remain
trusted project configuration. See [project preparation](coding-boundary.md).

## Coding build artifacts

Successful project validation can capture bounded root `dist` output as a ZIP
within its owned native process and existing worktree lock. The worker verifies
report identity, size/hash and ZIP members before registering an ordinary archive
Artifact. Coding/Work link to its download and Library provenance. No server or
HTML execution is added. See [the contract](coding-build-artifacts.md).

## Repeating Coding checks

The typed Coding check action enqueues another ordinary `project_validation` Run
on the same Task/worktree. It freezes the previous validation's recorded commands
and manifest snapshot, preserves earlier history and creates no inference or
dependency stages. See [check reruns](coding-rerun-checks.md).

### Bounded cumulative coding review

Source discovery excludes only untracked reserved root validation/dependency scratch directories at the Git scan. External model context and local review are separate contracts: ten selected files at 32,000 bytes each / 64,000 combined versus 200 review files at 256,000 bytes each / 2 MiB combined. Local AI uses the separate larger source policy below. The Runner computes the projected task-base diff before applying a proposal, bounds base blobs and the encoded 1 MiB report, then rechecks source snapshots and task branch/HEAD. Reviewed commit verifies the same broader snapshots using its private index. This permits generated lockfiles and multi-turn projects without increasing source sent to providers. See [coding continuation review](coding-continuation-review.md).

[Local source context](local-coding-source-context.md) is a native Local AI policy,
separate from external source sharing: ten paths / 256000 bytes combined, bounded
line-window exploration and hash-checked unique snippet edits for large files.
A dedicated text-only Coding bridge reuses existing owned-runtime identity,
streaming and disconnect contracts; ordinary Chat/vision limits are unchanged.

[Independent video shots](parallel-video-shots.md) remove unnecessary motion
dependencies only for shot-mode windows. GPU/host RAM admission and owned
process/lease contracts remain unchanged; continuous video/avatars retain prior
motion edges. Final composition and lineage use timeline order, while partial
preview uses completion time. Shared job projection exposes current running,
queued and active-stage GPU state to the conversation and media workspace.

## Automatic local-agent workspaces

[Managed agent workspaces](agent-workspaces.md) compose the existing typed project
setup with a bound Local coding workflow. A reviewed project-free local agent may
provision one app-owned project; later executions reuse its registered identity
and create fresh worktrees. Original definition snapshots remain immutable.
## Data inputs

[CSV/XLSX input previews](data-inputs.md) use the artifact store and the ordinary
worker queue. Trusted bounded read-only parsers operate on verified app-owned
bytes in a control-plane worker, without host access, network or user code.
Generated Python execution remains the separate isolated native-runner container
boundary; metadata inspection does not grant that permission.

## Context-aware Chat search

Ordinary Chat enables its visible search switch by default, with a versioned
operator preference for opt-out. HTTP APIs still require per-request selection.
Work tasks retain their explicit network scopes. The worker resolves automatic
follow-up subjects from a frozen, bounded ordinary-text window before retrieval;
manual queries bypass resolution. Only the short query reaches SearXNG. Actual
queries, original follow-ups and source artifacts remain auditable; cancellation
and failed resolution stop retrieval. See [web search](web-search.md).

## Local data-agent execution

[Python data agents](python-data-agents.md) reuse ordinary agent workflows,
automatic private projects, owned worktree preparation and the existing offline
Python executor. Local source generation and result verification are separate
Runs; script, inputs, raw outputs and a literal CSV download are ordinary artifacts.
The original workflow deadline, Task Stop and frozen definition cover repairs.
No unrestricted filesystem or shell API is activated.

## Planned agent website preview

[Interactive site preview](agent-site-preview.md) executes generated JavaScript
inside an owned network-disabled Chromium workload, returning PNG frames and
accepting only typed revision-bound interactions through ordinary Runs. It is
unpublished until permissions, resource admission, process ownership, Stop,
recovery and real browser/agent acceptance pass. No generated script executes in
the authenticated UI origin; no public preview port is introduced.


[Reviewed email delivery](reviewed-email.md) is being qualified as a control-plane
SMTP connector. It reuses SecretProvider references, operator previews/approvals,
ordinary Tasks/Runs and a durable delivery journal; no Host Runner or shell API is
needed for SMTP. Automated agent email remains a separately scoped integration.


### Stock-data account execution

[Stock agents](plans/stock-price-agents.md) extend the deterministic price workflow.
Named `market_data` connectors store write-only Finnhub credential references.
Handlers enqueue account-check/symbol-search Runs; `market_feed` workers use fixed
DNS-pinned endpoints and return canonical bounded artifacts. Stock quote children
require both network-read and account-read permissions. The selected account
revision, symbols, provider timestamps/currency/session and approval scope are
frozen and revalidated before notification. Migration 0031 adds source metadata
without replacing crypto history or changing its policy hashes/template IDs.
Deployment requires full local qualification and reviewed integration through develop.


Goal-based vocal agents extend the existing local media preparation with an
explicit reviewed lyric-writing mode. One bounded JSON preparation produces the
caption and original song text; the existing music Run receives finalized words.
Supplied lyrics retain their default exact-word contract. UI and Library preserve
the actual words, while Task ownership, immutable expiry, Stop and publication
receipts reuse [the media-agent contract](plans/agent-media-generation.md).


Conversation original-song writing reuses the existing orchestrator Run before
its atomic music-child publication. Shared pure text schemas match agent song
preparation; ordinary provider snapshots, grants, model admission, leases and
Stop bind creative inference. Prepared JSON and final WAV preserve provenance.
Instrumental/supplied words retain their no-text-model path. There is no new
executor, persistent transient agent or native API; see
[the conversation contract](plans/conversational-music.md).

Agent cron schedules resolve reviewed IANA wall-clock rules into durable UTC due
instants through the existing scheduler. Daily/custom controls share the same
contract in Agents and conversations; legacy schedules retain UTC. See
[calendar scheduling](plans/agent-schedule-timezones.md).

[Explicit natural data follow-ups](plans/conversation-data-references.md) resolve
current-user file references to a verified completed same-conversation analysis.
Controller-owned source/context/input snapshots feed the existing private data
workspace pipeline. Each question has a new Task/deadline; quoted prior context
adds no tool authority. No new executor or native API is introduced.

## Reviewed research for offline data agents

[Research/data composition](plans/agent-research-data.md) reuses public source
Runs and their existing verified context handoff before the ordinary Python data
workflow. One bounded JSON Artifact contains complete saved observations and
source lineage. It becomes an immutable read-only input beside optional CSV/XLSX
files; Python remains offline. The original agent definition, Task, private
workspace, deadline, Stop and repair budget bind every stage. No new executor,
native API, dependency or database migration is introduced.

## Public data analysis in conversations

[Conversation research/data](plans/conversation-research-data.md) extends the
existing file-analysis scope with explicit reviewed public query/URLs. The
ordinary agent-free workflow reuses verified research, one inspected JSON capture,
owned project/worktree, local generation and offline Python. Each source child
checks its exact conversation/message/scope/dependency before a public request.
Completed captures can become ordinary offline inputs on a later conversation
Task, with their original attribution rechecked. Explicit refresh creates another
source snapshot. No persistent Agent row or new execution engine is introduced.

[Captured-source context](plans/captured-data-context.md) reuses verified response
excerpts when a capture becomes an ordinary offline input. These bounded,
explicitly partial previews expose response bodies beyond generic nested-cell
prefixes; code still reads the complete input and inherits no public tool scope.

## Offline metadata recovery

Database replacement belongs to the host operator lifecycle, never a worker or
request handler. `scripts/station_recovery` separates read-only inspection/private
normalization, host quiescence, durable atomic replacement and explicit CLI input.
Alembic supports an injected staging connection without touching the configured
live engine. Pending receipts cooperate with the launcher lock/startup guard.
Normal Tasks/Runs/Events/Artifacts remain the workload architecture; recovery
adds no execution service or shell endpoint. [Recovery contract](plans/offline-database-recovery.md).

[Reviewed multi-hour agent budgets](plans/long-media-agent-budgets.md) extend the
existing absolute deadline contract to at most four hours. A pure backend limit
is shared by definitions, proposals and media publication; native owned-process
admission enforces the same finite ceiling. The shared UI selector preserves
exact saved seconds. This adds no executor, schema change, permissions or resource
capacity; child publication and replay keep the original expiry.

## Memory-aware local execution

[Scoped memory context](plans/agent-data-memory.md) reuses existing context child
Runs, immutable JSON observations and the offline Python/local coding handoff.
Optional data-result retention uses the existing MemoryEntry service after result
validation, in the success transaction. No new schema/native executor is added.

## Selected agent documents

[Read documents](plans/agent-document-context.md) adds a scoped registry context
step to existing report, offline code/data and goal-based media workflows. API
handlers validate/store uploads and enqueue as usual; only the worker extracts.
A fixed short-lived Python helper receives verified bytes on stdin, fixed format
arguments and a minimal environment. CPU/address-space/wall/input/output limits,
owned process-group Stop/reap and Linux parent-death signaling bound its lifecycle.
This is a fixed parser inside the control plane, not a generated-code executor or
new host filesystem API. The existing native offline Python receives only verified
captured text. Migration0035 adds nullable agents.documents; absent scope is omitted
from frozen definitions to preserve legacy consent/receipt identities.

## Conversation document analysis

The existing Files & data turn can carry the same selected-document scope as an
Agent. Metadata snapshots bind the current message and orchestration Run; worker
byte checks precede workspace creation. The ordinary source/context/Python graph
runs with no Agent row. Context tools order documents before public research and
retain per-source permissions. Follow-ups adopt immutable capture inputs through
the existing data reference service, without renewed document/network authority.
Absent document scope is omitted from legacy identities. No migration, native
protocol or second execution engine is added; see
[conversation documents](plans/conversation-document-context.md).

## Source-bound analysis agents

An explicit Work request to repeat the latest completed conversation analysis uses
the existing agent_draft child Run. The controller freezes and rechecks the visible
same-conversation result, source scope, input/inspection snapshots, verified result
artifacts and original definition. A restricted model proposal supplies identity and
schedule; source tools, local data model, goal and inputs remain controller-owned.
Publication uses the shared settings mapper, a definition JSON artifact with source
lineage and the existing atomic disabled-Agent/terminal-Run transaction. No schema,
native protocol or separate execution engine is introduced. See
[analysis-to-agent design](plans/conversation-data-agent-draft.md).

The [selected-analysis action](plans/analysis-agent-action.md) adds an optional typed
conversation message reference and a focused schedule dialog to the same draft
service. Exact same-conversation root selection replaces latest-result lookup only
when explicitly supplied; all existing source verification and execution apply.

[Direct selected-input drafts](plans/selected-input-agent-draft.md) normalize an
explicit Work creation request before one-off analysis dispatch. Existing data
selection becomes frozen user/orchestrator/agent_draft metadata. The existing
factory proposes bounded identity/task wording/schedule and publishes a disabled
Agent. No new executor, native protocol, database table or preliminary data Run.

[Selected-agent families](plans/selected-agent-families.md) extends only the source-
bound factory proposal. Document/public-only scope admits controller-mapped data,
report or local-code recipes; data files and instruction-only creation retain the
data recipe. Source snapshots and existing AgentSettings remain unchanged. The
controller maps tools/models/workspace policy, and normal explicit activation
starts the existing report or code/data workflow. No new execution system/schema.

Operator startup recovery stays outside agent tools and the Docker control plane.
The [recovery utility](operations.md#recovering-an-api-port-after-network-startup)
repairs a failed publish mapping only for the validated owned API and its existing
image. It does not stop running workers, restart native executors or apply an
upgrade.

## Private saved media timelines

Video editing extends CreativeSession with capability `timeline`; immutable
TimelineRevision rows own no independent execution architecture. Each revision
belongs to its private workspace and freezes source observations and a typed
frame/sample manifest. Ordinary CreativeTurns enqueue `timeline_render` Runs;
the worker reserves RAM and dispatches the native CPU renderer through the
private Unix socket. Waveform analysis is a bounded ordinary container Run.
The native renderer verifies source hashes, timing and output coverage before
publishing a general video Artifact. Preview and export reuse the same verified
result; changed drafts cannot export an earlier mix as their current edit.
See [timeline plan](plans/media-timeline.md).

Sound-effect media agents reuse the shared pure `EffectsRequest` contract and
existing `create_effects_run` service. Agent preparation freezes the selected film
and cues, and passes its trusted engine preflight into transactional child
publication. GPU sound generation and CPU preview remain ordinary existing Runs;
no agent-specific process or separate execution engine is introduced. Final
media-result summaries recognize only the verified effects preview.
