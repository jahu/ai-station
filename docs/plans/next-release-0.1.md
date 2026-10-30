# Next release: private accounts and creative workspaces

Owner direction, 2026-10-29, after v0.0.2. Target milestone: **0.1.0**. This is
the implementation contract for the complete supplied change list, not a claim
that the features below ship. Preserve the existing application and qualified
media profiles. Product version remains 0.0.2 until release preparation.

## Scope and acceptance

| ID | Requirement | Observable acceptance |
| --- | --- | --- |
| NR-01 | Persistent creative conversations in Images, Video, Music, Speech and Avatars | Start a job, navigate away, return to the same saved workspace, refresh/restart and retain history, inputs, progress and results. A follow-up creates a new linked variation with the feedback and chosen previous result; it never overwrites earlier work. |
| NR-02 | Progress and remaining-time estimates for every generator | Each active job shows queued/preparing/generating/finishing state, actual measured progress when available and an honest estimate/range. Refresh retains it; saving is not success and unknown progress is not a fabricated percentage. |
| NR-03 | More reliable structural image editing | Neutral pose-change/object-removal fixtures are actually changed. Auto can recommend/select a qualified Qwen path for structural instructions; explicit LUSTIFY choices remain visible and honored. Compare real same-source outputs rather than claiming every model follows every instruction. |
| NR-04 | Optional local prompt improvement | A checkbox in generative workspaces creates a durable local LLM preparation Run. The actual improved, model-specific prompt is used downstream; original/effective prompts, model and template are inspectable. Preserve intent, protected words and selected content freedom. |
| NR-05 | Dismiss completed Library deletion cards | X visibly removes that exact completed card, remains dismissed after navigation/reload, never deletes its Run history, never cancels an active deletion and reports persistence errors. Older identical cards do not immediately replace it. |
| NR-06 | Expressive local TTS | Real neutral/happy/sad/fearful/whisper/pace comparisons retain complete words and demonstrate audible expression. Polish remains usable. Styles and nonverbal tags appear only for engines actually supporting them; voice cloning remains an explicit source. |
| NR-07 | Generated synchronized scene audio | Describe the sounds of each scene; create a separate local effects/ambience stem, aligned to the actual video. Speech and musical score remain separate tools rather than simulated sound effects. |
| NR-08 | In-platform video/audio editing | Persist a timeline with source clips and independent speech/music/effects tracks; trim, move, reorder, adjust volume/fades/mute, preview and render a verified synchronized film. Earlier timeline revisions/results remain available. |
| NR-09 | A suitable product name | Record a short naming shortlist, availability checks and the selected direction. Apply accepted branding consistently to UI/site/docs/installers without breaking data paths, URLs or project identities. |
| NR-10 | README model freedom and user responsibility | Explain compatible user-selected uncensored models/NSFW use, local execution and responsibility under applicable law/licenses. Do not claim universal format support, automatically uncensored behavior or absolute legal immunity. |
| NR-11 | Real accounts, private data and optional 2FA | First startup creates an admin; admin manages users and can inspect all data. A/B users cannot enumerate or access each other's prompts, chats, Library, files, memory, agents, Runs, projects, settings or credentials through any API/UI/tool. Password/cookie sessions and opt-in TOTP/recovery work. Only infrastructure/model resources are shared. |
| NR-12 | LLM-prepared Web searches | A local, tools-free preparation step derives relevant queries from the current question and bounded relevant conversation. Search uses those queries, displays them and returns sources relevant to ambiguous follow-ups. Explicit URLs still use page reading. |
| NR-13 | Easy installation on Windows, macOS and Linux | A nontechnical user installs the application, creates the admin, selects fitting capabilities and obtains a real first result through a guided flow. Update/uninstall retain user data unless explicitly removed. Test every advertised platform. |
| NR-14 | Hardware-aware model catalog and setup | Detect actual RAM/VRAM/devices, recommend compatible model/quantization/context profiles with headroom, show size/license/storage before download, and configure real readiness. Advanced users can search/select alternatives. Verified downloads recover from cancellation/restart and stale URLs without substituting unverified weights. |

These are all in scope. A partial Linux installer, an emotion selector with no
audible effect, cosmetic progress or workspace-local component state does not
satisfy the corresponding requirement. Unfinished adapters remain unavailable.

## Delivery order

1. **Foundation and visible defect:** record this plan and fix NR-05. Retain the
   v0.0.2 release/tag and owner working changes. The current Library has 15
   completed purges: filtering dismissals before taking the next three makes X
   replace a card with an older identical card; component-local dismissal also
   vanishes on remount. Persist a terminal Run's presentation dismissal and keep
   a stable recent window; retain execution history and outcomes.
2. **Account isolation, NR-11:** inventory all routes and data owners, introduce
   migrations and principal/session services, then enforce ownership throughout
   APIs, workers, tools and browser caches before offering additional accounts.
   Add optional TOTP and administrator controls. Existing operator data migrates
   to the bootstrap admin without losing password access or files.
3. **Creative workspaces, NR-01/02:** owner-scoped saved sessions and turns around
   existing Tasks/Run graphs; sidebar/history and restored drafts in every media
   workspace. Add consistent progress projection, then real executor progress
   extraction and estimates scoped by model/profile/geometry/hardware.
4. **Prompt and search quality, NR-03/04/12:** extend existing local translation
   preparation rather than adding a second job engine. Add model-specific prompt
   improvement, source-aware image routing and local search-query preparation.
5. **Sound and editing, NR-06/07/08:** short real model/style auditions, qualified
   typed TTS/SFX adapters, then saved multi-track timeline/rendering. Integrate
   workspace feedback, cancellation, resource scheduling and artifact lineage.
6. **Consumer setup, NR-13/14:** curated catalog/download service, capability
   onboarding and packaged desktop launcher/installers. Qualify clean Linux,
   Windows and macOS paths with actual platform evidence.
7. **Brand/docs/release, NR-09/10:** finalize naming and responsibility copy,
   refresh setup/benchmarks and issue an updated release-specific QA workbook.
   Review the complete candidate before the human-approved master promotion.

Independent work can proceed between gates. Do not enable a new multi-user
surface while any private route/tool still reads globally.

## Accounts and data ownership

Add `User`, revocable hashed-token `UserSession`, TOTP enrollment/recovery and
owner references through Alembic. Preserve the existing password hashing policy
and use a mature TOTP implementation. Never log passwords, enrollment secrets,
recovery codes or cookies. TOTP secret material needs protected server-side
storage and an explicit backup/recovery contract; recovery codes are hashed.

Every private root has an immutable `owner_id`: conversations/creative sessions,
Tasks/Runs, artifacts/uploads, projects/worktrees, agents, memory, notices,
approvals, connectors and personal settings. Children inherit and validate the
same owner; cross-owner source references are rejected, including admin-mediated
execution unless an explicit administrative operation is intended. Existing
records/files are backfilled to the bootstrap admin. Do not rename/move media
bytes merely to introduce ownership. App paths remain relative to the data root.

Model files/definitions and physical runtime/resource inventory are shared.
Private prompts, logs, model conversation state, credentials and task identities
are not shared telemetry. Ordinary users may consume approved shared models but
not alter machine configuration or inspect another user's managed workload.
Admin access to private data is explicit; being admin does not silently grant
all tool permissions to an agent.

Authorization belongs at repository/service boundaries, not only React filters.
Build a route/operation inventory covering list/detail/search/count endpoints,
SSE/reconnection, downloads/Range/thumbnails, lineage, FTS/embeddings, previews,
notices, approval/retry/cancel, scheduler launches and native dispatch. Missing
principals fail closed. Workers act for the frozen Run owner, not an ambient
administrator; runners receive only validated source/run authority. UUID secrecy
is not authorization. Shared runtime output must not expose another user's text.

Use HttpOnly, SameSite cookies, secure flags under HTTPS, expiry/revocation,
same-origin mutation protection and login throttling. No public registration by
default. Handle first-admin bootstrap, existing-operator migration, password
changes/reset, user disable/deletion, last-admin protection and per-device logout.
Clear/invalidate all private query/draft/object-URL caches on account changes;
browser storage must be account-scoped. An admin can inspect all accounts as
requested, while normal users only see their own global memory scope.

Do not roll this migration onto the owner's live data until temporary-database
legacy migration, preservation and A/B/admin negative-access tests pass. The
current single-operator service continues unchanged until that gate.

## Creative sessions and prompt preparation

Add owner-scoped `CreativeSession` and append-only `CreativeTurn` records with
capability, title, saved draft/options, source/result IDs and Task links. A session
is a UI/domain grouping, not another executor. Each generation/follow-up retains
ordinary Task → Run → Events → Artifacts and immutable input/profile snapshots.
Resume the exact session route after navigation; an explicit New action opens a
fresh session. Show in-flight jobs, feedback and prior versions together.

A follow-up names its selected version and retains all earlier artifacts. Only
permitted inspected inputs and bounded relevant turns enter an LLM prompt. A
thumbnail/reference is not automatically a textual description of its content.

Reuse the translation preparation/review pattern for optional enhancement:
original → model-specific local improvement/translation → frozen effective
prompt → normal generator. Include local model/template identity, retained
meaning/protected tokens and a visible inspect/edit result. No hidden external
provider, model refusal override claim or secret prompt expansion. Canceling or
retrying preparation must not duplicate generation. Exact narration, lyrics and
quoted text are preserved unless separately authorized for rewriting; avatar
motion/scene enhancement must never silently change the spoken script.

Progress estimates use persisted measured events and comparable completed
profiles, with stale/insufficient-data handling and separate preparation,
generation, interpolation/encoding and queue/resource wait. GPU telemetry is not
percentage completion. Unknown stage progress is indeterminate with an honest
estimate range; a reliable determinate bar needs executor observations.

## Speech, scene audio and editing

Audit the actual installed Chatterbox CLI and style controls before changing it.
Do not modify the external runtime or reuse an unsupported style label. An
upstream report of weak multilingual exaggeration is a research lead, not proof
of our installation's root cause. Preserve the current working Polish path.

Candidates checked against primary upstream sources on 2026-10-29:

- [Chatterbox](https://github.com/resemble-ai/chatterbox) exposes expressiveness
  and pacing controls; audition their real effect with the installed model.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) offers instruction-controlled
  1.7B voice variants, but its documented ten languages omit Polish. It cannot
  silently replace Polish narration. Evaluate only supported-language profiles.
- [Fish S2 Pro](https://huggingface.co/fishaudio/s2-pro) advertises inline emotion
  and Polish among its languages. Its roughly 11-GB weight set is not proof of
  fitting a 12-GB GPU; qualify actual peak allocations/precision and its separate
  model license before recommendation.
- [MMAudio](https://github.com/hkchengrex/MMAudio) supports text/video-conditioned
  effects. Its authors report about 6 GB for their half-precision demo, not our
  measured requirement. Qualify short per-scene generation before longer mixes.

Freeze code/weight hashes and limits for every accepted adapter. First render a
short, neutral, reproducible audition; check complete words, language, audible
style, duration, allocation, cancellation and output decode. Only then run a
longer recording. Keep stems and the exact original text as provenance.

Represent timeline edits as typed, versioned clips/tracks: artifact IDs, source
in/out, timeline start, gain, mute and bounded fades. Never accept an arbitrary
FFmpeg filter graph or command from a user/model. The native compositor builds
fixed argv from the validated manifest. Preview and final export use the same
timing model. Show actual waveforms/clip positions and allow drag/trim plus
keyboard/numeric controls. Effects, narration and music are separately generated
and scheduled, with sample/frame accounting, optional ducking, clipping checks
and no silent truncation. Every render retains the manifest and input lineage.

## Installers, catalog and automatic setup

Keep Docker control plane + dedicated native user Runner. Add a small desktop
launcher/onboarding shell around the same web UI; avoid a second application
backend. [Tauri's packaging targets](https://v2.tauri.app/distribute/) are a
candidate for Windows/macOS/Linux installers, subject to a packaging prototype.
Linux uses the existing native Runner/private UDS. Evaluate Windows through a
managed WSL2 user environment and Docker integration; macOS needs a native Runner
and qualified CPU/Metal-compatible runtime paths. Do not advertise CUDA-only
media as working on every GPU/vendor. Test the actual chosen transport and file
boundaries on each OS, not just mocked OS strings in Linux tests.

The first-run flow is hardware → admin → choose capabilities → recommended
profiles/downloads → real readiness → first result. Show download sizes,
storage, licenses and expected memory/context. Advanced search/quantization
controls remain available. Configure managed defaults without .env editing.
Missing optional prerequisites need a guided explanation/action; OS permissions,
external prerequisite licenses and GPU-driver changes require explicit local
operator consent. Never change this development workstation's drivers or OS as
an installation test.

Catalog entries bind publisher/repository/revision, SHA-256, format, model family,
license, capabilities, tested runtime/platform, quantization, memory/context
envelope, download sizes and required companion files. Use the existing registry,
resource admission and explicit download Runs. Native installation creates only
app-owned environments; do not execute arbitrary model-repository Python or
silently install missing weights during inference. Reuse verified existing files.

Downloads need staging, disk checks, cancellation, resumable ranges, hash checks,
atomic publication, progress and restart recovery. For stale links, first resolve
the same publisher/revision/file and verify the expected hash. Search results or
a mirror URL are not authority to replace a model or license. Changed bytes
need an explicit catalog/review update. Record unavailable/gated sources honestly.

Qualify clean-machine install → admin → recommended download → first real
completion/media artifact → restart/update → retained data on Linux, Windows
and macOS. Signing/notarization and platform hardware evidence are release gates
for the installers that claim them, not reasons to stop independent application
work while a platform-specific credential/device is unavailable.

## Naming and README

Working name stays AI Station during implementation. Candidate directions:
**Ownspace** (personal workspace), **Ognivo** (connected tools, Polish character),
and **Localia** (local creation). These are proposals, not availability/trademark
claims. Check product/domain/package collisions before an actual rename; the
owner can choose without blocking account/media work. Keep storage/application
identifiers stable if display branding changes.

Explain compatible uncensored models and adult content plainly, with behavior
determined by the chosen model/runtime. Describe user responsibility for inputs,
outputs, permissions and applicable law/model licenses. Reference the existing
[license](../../LICENSE) and its
[upstream no-liability terms](https://polyformproject.org/licenses/noncommercial/1.0.0).
Do not promise that prose removes every legal responsibility or that all model
formats run already. No private/NSFW Library material enters public showcases.

## Release proof and tracking

For every NR item retain implementation PRs, exact-head checks and real execution
receipts where appropriate. New ownership/session/timeline schema uses Alembic.
Normal tests use temporary databases, fake inference and synthetic neutral data.
Real model/platform qualification is explicitly opted in and separately recorded.

The account gate needs A/B/admin denial tests for every inventoried surface,
including worker tools, media sources and browser account switches. Creative
sessions need navigation/reload/restart and meaningful feedback/source reuse.
Media needs actual progress, cancellation/recovery, no partial publication and
complete output checks. Installer/platform claims need real platform evidence.
Extend the operator workbook as a new version; never rewrite issued v15 results.
Preserve the normal full local backend/Runner, UI, Docker/Compose and fake-worker
gates. The human owner still approves/merges master; tags remain immutable.

First qualified increment: NR-05 has durable terminal-only dismissal, a stable
recent-card window and visible rollback on save failure. Full normal coverage
passes: 4757 Python/Runner cases and nine opt-in skips, 891 frontend tests, global
format/lint/types/build, Docker/Compose and actual isolated image/worker/API and
compiled desktop/mobile browser checks. Private evidence:
`data/acceptance/release-0.1-foundation-20261029/`. Deployment is tracked separately.
NR-10's model-freedom/responsibility README update is also merged to `develop`.
NR-11 is in active implementation: staged ownership, private request/execution
sessions, account/security UI, recovery, shared-model coordination, Docker-local
first-admin setup and account-aware private-connection operations have separate
synthetic/local qualifications. The shipped application still uses its existing
operator profile. Administrator inspection now has a staged selected-account,
read-only UI with collection/detail/message/event and media access; its complete
profile qualification remains part of cutover. The complete operation audit,
remaining legacy execution-path removal and final preserved-data cutover remain
enablement gates; see [account contracts](../accounts.md). The latest inventory
contains 222 HTTP operations (214 API) and 35 ORM tables; enumeration alone is
not an isolation pass. Other NR items remain open and research candidates remain
unqualified. These increments do not complete the full next-release scope.
