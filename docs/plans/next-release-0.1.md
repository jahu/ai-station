# Next release: private accounts and creative workspaces

Owner direction, 2026-10-29, after v0.0.2. Target milestone: **0.1.0**. This is
the implementation contract for the complete supplied change list, not a claim
that the features below ship. Preserve the existing application and qualified
media profiles. Product version remains 0.0.2 until release preparation.

## Scope and acceptance

Current NR-06 implementation adds an optional Fish S2 Pro voice alongside the
existing Chatterbox path: Audio and reviewed speech agents expose model,
direction and pace, restored in private creative history. Real integrated short,
three-chunk long and scoped-cancellation tests pass on the local GPU pair.
Audible style/fidelity acceptance remains open; this is not completion of NR-06
or this release. See [the measured speech contract](expressive-speech.md).

NR-14 now includes a qualified [guided music profile](managed-music-setup.md),
following conversation, speech, images and CPU memory setup. It reuses ordinary
Task/Run preparation and the existing music executor; real first-account
installation, Stop/Resume, first-track Library playback, native restart/Stop and
account denial passed privately. It does not close video/avatar/effects setup,
broader hardware/catalog choice or the consumer OS installer requirements.

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
| NR-12 | LLM-prepared Web searches | A tools-free preparation step uses the selected permission-bound model (local by default; external only when explicitly selected) to derive relevant queries from the current question and bounded relevant conversation. Search uses those queries, displays them and returns sources relevant to ambiguous follow-ups. Explicit URLs still use page reading. |
| NR-13 | Easy installation on Windows, macOS and Linux | A nontechnical user installs the application, creates the admin, selects fitting capabilities and obtains a real first result through a guided flow. Update/uninstall retain user data unless explicitly removed. Test every advertised platform. |
| NR-14 | Hardware-aware model catalog and setup | Detect actual RAM/VRAM/devices, recommend compatible model/quantization/context profiles with headroom, show size/license/storage before download, and configure real readiness. Advanced users can search/select alternatives. Verified downloads recover from cancellation/restart and stale URLs without substituting unverified weights. |

These are all in scope. A partial Linux installer, an emotion selector with no
audible effect, cosmetic progress or workspace-local component state does not
satisfy the corresponding requirement. Unfinished adapters remain unavailable.

The guided Images increment qualifies one Linux NVIDIA profile with five pinned
companions, ordinary Generate/Edit/Recompose/Upscale, private saved setup history,
real GPU Stop/recovery and desktop/mobile first-result checks. See
[image setup](managed-image-setup.md). It advances NR-14; it does not complete
other media catalogs or the NR-13 cross-platform consumer installation contract.

Guided video is reviewed, merged and deployed (PR #542), including actual
installation, first scene/image animation, a continuous film, final composition,
CPU editor export, native recovery/Stop and private shared-engine checks.
[Guided avatars](managed-avatar-setup.md) are the current NR-14 increment:
independent preparation, complete two-second generation, recovery/Stop, privacy
and final packaged/default-policy checks have passed. Review, merge and deployment
are the remaining gates for this profile.
Consumer installation on all three operating systems, remaining sound setup,
broader model selection and NR-06/07 quality acceptance remain in scope.

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
5. **Sound and editing, NR-06/07/08:** follow the [synchronized sound/editor contract](synchronized-sound.md); short real model/style auditions, qualified
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

The next implementation contracts are [measured generation progress](generation-progress.md)
and [optional local prompt enhancement](local-prompt-enhancement.md). Both extend
the existing worker and media preparation lifecycle.

Add owner-scoped `CreativeSession` and append-only `CreativeTurn` records with
capability, title, saved draft/options, source/result IDs and Task links. A session
is a UI/domain grouping, not another executor. Each generation/follow-up retains
ordinary Task → Run → Events → Artifacts and immutable input/profile snapshots.
Resume the exact session route after navigation; an explicit New action opens a
fresh session. Show in-flight jobs, feedback and prior versions together.

Implementation uses one shared history/draft UI around the existing five forms;
generation stays typed and transactional with its saved turn. Preserve both
short direct Runs and the existing full-film/full-recording MediaJob variants
(`media_jobs.py`); the new UI must not narrow Video or Sonic avatar functionality.
History progress and Stop follow the complete owned Task graph, including speech,
translation, continuation and composition children. A preparation Run succeeding
does not mark the complete turn successful. Reuse the existing Task cancellation
service. Draft saves are versioned and serialized; navigation/reload flushes pending
changes without allowing a late save to cross accounts or overwrite a new turn.
Source/variation controls restore validated request fields, not arbitrary Run
parameters, and preserve exact narration/lyrics unless the user explicitly edits them.

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
NR-11 is qualified, reviewed, merged in PR #512 and deployed on the workstation.
Private roots, inherited records, credentials, preferences, workers, schedules,
files/SSE and browser state are account-bound; models and physical resources stay
shared. Login/devices/TOTP/recovery, administrator management and explicit read-only
workspace inspection are operational. The account profile refuses unbound/ownerless
execution and operator fallback after activation. Its 397-case complete account
gate, 82 additional native/API regressions, 928-case frontend qualification,
compiled desktop/mobile checks and packaged API/separate-worker tests passed.
The actual 0036 → 0038 cutover preserved existing content, credentials and private
owners with a fresh backup, without restarting the native Runner or models.
See [account contracts](../accounts.md) and the [surface review](../account-boundary-review.md).

NR-01 now has migration 0039, private sessions, bounded versioned drafts,
ordered append-only turns and atomic idempotent generation through all five
existing typed builders. Shared history, exact selected-source editing,
autosaved/restored forms, archive/restore and whole-Task Stop cover Images,
Video, Music, Speech and Avatars. Full films and whole-recording Sonic avatars
retain the existing MediaJob variants. Administrator inspection remains explicit
and read-only. [Workspace contracts](../creative-workspaces.md).

The frozen complete normal Python/Runner baseline passed: 5,092 cases with nine
opt-in skips across four disjoint complete-file cohorts. The 28-case final
creative/workflow/inspector families also pass after the subsequent backend
changes. Compiled desktop/mobile checks pass against a real account API and a
separate synthetic generation worker, including exact-source follow-up,
navigation/reload and foreign-user denial. This is not real model inference.
The complete 936-case UI baseline and final ten-case changed workspace family
pass, with format/lint/typecheck/build and Compose checks. The real compiled
UI check also caught and verified the fix for a fresh-cache submission conflict.
PRs #514/#515 are reviewed, merged and deployed. The 0038 → 0039 rollout
preserved all existing table contents and credentials with a fresh backup; native
Runner, private access and loaded models were not restarted. Actual production
desktop/mobile account UI checks passed with an audited temporary device, revoked
after verification. Translation review/resource-wait controls retain their prior
behavior; their final 32-case component families pass without unhandled errors.
NR-01 is complete. NR-02 and the other remaining NR items stay open; this increment does not complete the full next-release scope.

NR-02 is reviewed, merged in PR #516 and deployed across creative history,
direct results, full MediaJobs and Run details. It persists actual sampler/chunk
observations and private comparable-job duration ranges, distinguishes final
saving/checks from sampling completion and hides stale estimates. Existing Sonic
global progress remains intact. The [progress contract](generation-progress.md)
records baseline/final-family, compiled browser and production rollout evidence.
The preserved-data rollout left the native Runner/models running. NR-02 is
complete. Optional prompt enhancement is implemented for image, Wan, music and
Echo descriptions. Its 687-case affected backend families and 951-case frontend
suite pass; final accessibility changes have 37 passing complete-family cases.
Compiled desktop/mobile preparation, review/edit, effective generator input,
receipts, retained history and private-user denial pass with synthetic inference.
PRs #517 and #518 are deployed. Real local Qwen preparation followed by LUSTIFY
generation succeeded with the exact prepared prompt and saved provenance. A final
frontend follow-up verifies that checking enhancement alone submits it without
requiring translation or review (40 component cases and compiled desktop/mobile
flow). NR-04 functional acceptance is complete; this is not a broad model-quality
benchmark. The remaining NR items stay in scope.

NR-12 automatic search is implemented and qualified: the selected admitted Chat model
prepares the first query before retrieval, with bounded ordinary-text follow-up
context, recorded query/model provenance, visible Sources details and cancellable
tools-free JSON generation. Manual queries, reviewed agent/image research and
page reading preserve their scopes. Synthetic search/caller qualification is
separate from real-model relevance evidence. Explicitly selected external models
reuse their existing permission grant and remain labelled external; no separate
planner setting or hidden model load is introduced. See
[search contracts](../web-search.md).

The real selected-model NR-12 regression passed on 2026-10-30: the deployed
unified assistant prepared both an ambiguous initial question and its short
follow-up using the local 27B llama.cpp model. Each retrieved five relevant
subject-specific sources and retained query/model/source provenance, without
the previously reported generic or unrelated results. The actual QA model and
temporary devices were cleaned up. See [search qualification](../web-search.md#selected-model-search-qualification-2026-10-30).
This completes the functional NR-12 gate for the reported regression; it does
not assert that search snippets independently verify every factual claim.

NR-07 basic effects generation and saved sound workspaces are deployed after
reviewed PR #524. Actual eight-second and fifteen-second/two-window inference,
linked previews and scoped Stop pass. Per-scene descriptions are deployed in
PR #526. Reviewed media-agent output is deployed in PR #528, with private film
selection, saved scene cues, ordinary effects/preview Runs and existing workflow
approvals/Stop. Conversation existing/new-film orchestration and default original-audio layering
are reviewed, merged and deployed in PR #529; perceptual
acceptance remains. See the conversation delivery contract below.
NR-08 multitrack editing is reviewed, merged in PR #527 and deployed. Private
revisions, trim/move/reorder, audio gain/fades/mute, measured waveforms and verified
CPU preview/export pass API/worker/native and compiled desktop/mobile qualification.
Actual scoped Stop, preserving migration 0041 and restoration of earlier edits
are verified. Source media and prior results remain intact. See [timeline contracts](media-timeline.md). [Deployment and remaining contracts](synchronized-sound.md).


NR-13/14 now have deployed Linux guided model/runtime preparation in PRs
#530–#532: pinned resumable model downloads, relative owned model coordinates,
native adoption, hardware/context recommendations, private histories and a
journaled fixed-image runtime installation. Actual Q4 hashing/adoption/GPU
responses, runtime transfer Stop/Resume/recovery and preserving-data upgrades
are qualified. Six reviewed 4B/8B/14B Q4/Q8 profiles have local search/fit filters;
the four larger GGUF headers are checked, without a full-weight inference claim.
The next [desktop package candidate](desktop-installation.md) bundles Python
and the compiled app. Complete consumer prerequisite/setup/update/uninstall
journeys, Windows/macOS execution and multimodal/companion setup remain required.


NR-14's [managed speech increment](managed-speech-setup.md) now has a qualified
Linux NVIDIA account/API/worker/native/UI journey: fixed source/dependency/model
inputs, runtime-owned Python, offline installation, saved progress, Stop/Resume,
private receipts and an ordinary first CUDA speech Run. Configured external
Chatterbox remains authoritative. The compiled desktop/phone UI and saved WAV
restore after restart. Remaining guided media recipes and real cross-platform
consumer installation remain required; this is not release completion.
