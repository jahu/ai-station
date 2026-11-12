# Creative Studio: branded reels, presentations and films

User goal, 2026-11-11. This is the delivery contract, not a statement that the
feature is already available. Existing media generation and editing remain in
place. Do not replace this goal with a template-only demo or mark it complete
after the project registry or a successful synthetic render.

Owner quality clarification, 2026-11-11: materials must be professionally
art-directed social content, with dynamic images, actual video and purposeful
motion, not a sequence of text on colored backgrounds. Static shots remain
valid when they serve the brief. A simple typography render qualifies only the
rendering component; it cannot qualify the product or close this goal. Design
for a strong hook, retention, platform-appropriate rhythm and shareability;
never promise virality or fabricate engagement metrics.

## Experience

**Studio** is a creative workspace for repeatable publication-quality materials.
Create a project such as a business, a course or a personal brand, describe its
audience and style, and keep related materials together. No repository path,
Git configuration, technical rendering flags or Chat/Work mode is required.
Projects are optional: a standalone request can create a standalone material.

A project holds its name, recognizable names/domains, description and one
editable identity: palette, typography, visual direction, tone, audience,
language, editorial rules and audio direction. Defaults select reel,
presentation or film, aspect ratio, length and narration/music policy. Never
assume a particular business, person, subject or language. Logos and reference
media must use existing owned Library artifacts, not arbitrary host paths.

Each material has an independent brief, script, storyboard, editable scene
timing, sources, audio and render history. Explain the chosen project and format
before/alongside execution and allow override. A changed project applies to new
work only; historical plans/renders retain the exact identity version used.
Archiving preserves project, sources and history. Deletion must not orphan or
silently purge existing results.

The unified assistant uses its existing LlamaIndex ReAct controller. Supply a
bounded catalog of the current account's projects and typed operations; choose
by the prompt's meaning and project names/domains, not a growing regex router.
Do not guess across ambiguous projects. Project-free requests stay supported.
Standalone Studio and assistant requests must use the same planner/builders.

## Execution and quality

Task → Run → Events → Artifacts remains the only execution path. Plan with the
selected local provider, validate structured scene/script output, generate
requested assets with existing images/speech/music adapters, then render using
Hyperframes. Observe actual completed children before composing their outputs.
Voice, music, both or silence follow the user's intent and visible project
defaults. Never silently deliver a silent film when audio was requested.

Hyperframes supplies deterministic HTML motion graphics, typography, diagrams,
captions and transitions. It complements Wan footage, rather than asking a
diffusion model to draw readable text. Use pinned dependencies and a finite,
typed composition contract compiled by trusted code. Project text, model output
and downloaded content cannot supply executable scripts, package names, shell
commands, runtime flags, URLs or host mounts. Rendering executes behind a typed
native Runner operation, with owned process identity, resource reservation,
deadline, Stop, restart recovery and immutable output publication. No raw HTML
execution endpoint and no control-plane Docker socket.

Default publication sizes are 1080×1920 for reels and 1920×1080 for widescreen
presentations/films, square when explicitly selected. Render at deterministic
30 fps with readable text/safe areas; higher output quality must not be confused
with native diffusion detail. Use local fonts and frozen assets: no network or
missing CDN resources during rendering. Enforce per-scene text/contrast/layout
bounds, keep sources, and export a high-quality playable MP4 with verified
duration, frame count and requested audio. Track QA failures as real failures.
Check narration duration before finalizing scene timings; pad/extend scenes,
never cut words to satisfy an earlier guessed duration. Mix music below speech,
avoid clipping, and expose voice/music controls. Reuse existing voice leveling
and timeline audio primitives where appropriate. Avatar and generated-footage
insertion must retain source provenance, aspect fitting and actual timing.

The creative planner must act as a director/editor, not just a copywriter. Its
structured storyboard describes the hook, narrative beats, shot type, asset
brief/source, on-screen action, camera/framing, timing, transition purpose,
narration, captions, music and sound accents. Generate coherent original images
and actual footage through the existing adapters; reuse approved Library assets
where appropriate. Preserve brand and subject continuity through shared source
references. Distinguish intentional image motion/parallax from generated video
and disclose the actual source in the inspector. Add composition controls for
image movement, video trim and placement, overlays and transitions; do not
mistake a changing headline for a dynamic visual scene. Avoid an arbitrary quota
of video shots: choices should serve the brief, subject, desired pacing and
actual hardware budget. Keep planned visuals, generated media and final edit
inspectable and editable; retain successes when one generation fails.

Default quality targets publication, not the cheapest passing template. Full
material QA includes narrative coherence, a clear opening, variation in shot
scale/composition, temporal continuity, transition frames, text safe areas and
legibility, voice cadence, sound design and a coherent ending/CTA where useful.
Use representative complete branded reels and educational films for visual and
audible acceptance, not a screenshot of one title or a silent six-second test.

## Delivery sequence

1. Private creative projects, versioned brand/default settings, project-bound
   existing creative workspaces, immutable generation context, and a polished
   project browser/editor. Alembic migration and two-account regression tests.
2. Pinned Hyperframes renderer/preparation/diagnostics behind the native boundary;
   real typography/motion render, cancellation and recovery qualification.
3. Durable structured script/storyboard planner and editable material revisions;
   integrate actual speech/music children and final full-HD render. Preserve
   drafts, sources and previous exports. No inference in HTTP handlers.
4. Assistant catalog, typed project selection and material-creation tools,
   including standalone materials and follow-up revisions. Project inference is
   model-based, bounded and inspectable, with owner-validated aliases.
5. Existing avatar/video/image insertion and postproduction; useful review and
   export UX on desktop and mobile. Document exact platform prerequisites and
   delivery status. Do not advertise unqualified Windows functionality.

These are implementation increments; the complete user goal requires all of
the above, not only the first merged PR.

## Acceptance evidence required

- Create two differently styled projects, edit/archive/restore, reopen after
  restart, keep independent materials; no account or administrator-write leak.
- Concurrent/stale saves and repeated submissions cannot overwrite identity,
  duplicate rendering, attach foreign media or lose prior results.
- Same-project renders visibly share palette/type/tone; a second project has
  an independently recognizable identity. Generic subjects work equally well.
- From Chat, create a branded reel and a standalone reel, select widescreen for
  an educational presentation, and correct a project choice in a follow-up.
- Actual voiced, music-only and voiced-plus-music exports; inspect complete
  playback, captions, timing, intelligibility, music ducking and clipping.
- Real full-HD portrait and landscape Hyperframes exports with no clipped text,
  unreadable slides, blank frames or browser/asset errors. Inspect frames at
  transitions and throughout the film, not just the opening screenshot.
- Incorporate actual avatar and generated media into an exported presentation
  through the same owned workflow; inspect aspect and audio synchronization.
- Stop during planning, audio generation and rendering; restart observation
  without duplicate side effects; release only owned resources. Other GPU work
  continues and bounded waiting respects the existing deadline fixes.
- Backend/Runner checks, migration validation, frontend tests/lint/typecheck/
  production build, reviewed diff and local deployment qualification. Any real
  expensive run is explicit; ordinary tests use disposable data/fake adapters.
- Public showcase publication remains a separate owner approval; private test
  outputs belong in the account Library and must not leak into the website.

## Research

Official Hyperframes [CLI](https://hyperframes.app/docs/5-packages/cli) and
[source](https://github.com/heygen-com/hyperframes), inspected 2026-11-11. It
supports local frame-seeking render and HTML media tracks. Pin and inspect the
actual installed version before choosing command flags; do not install from a
moving `latest` during a render or reuse unrelated project runtime ownership.

## Current acceptance audit — 2026-11-12

The dated sections below retain earlier failures and qualification boundaries;
their historical “remaining” lists are not a current execution checklist.
Fresh renderer preparation, actual Stop/restart recovery and a first-use export
are qualified. Conversation-created portrait/music and landscape/silent outputs,
a standalone voiced reel, a complete educational voice/music film and an
integrated generated presenter have actual private Library evidence.

The educational film has now been revoiced and exported at 1920×1080, 2250 frames
and exactly 75 seconds, retaining all original visual sources. Independent local
transcription recovered all 179 words without edits. The owner approved pace,
expression and narrator continuity across the complete film. This supersedes the
95.633-second narration-quality rejection without deleting that earlier result.
[Performance and timing](studio-measured-timing.md) describes the generic changes.
Shared same-seed speech calls and a fixed generated-voice anchor apply beyond
Studio; supplied recordings retain their verified voice reference.

The conversation bridge now supports [source-aware revisions](studio-conversation-revisions.md).
Temporary-account tests cover parented edits, linked brand copies, exact source/
audio/presenter reuse, stale/foreign/archived/trashed authority and Stop isolation.
Actual local-model follow-ups changed only a headline in the existing 16-second
portrait film, then created a separate 1920×1080 copy under the other brand.
Both retained every actual shot/trim and the exact score, with no new media
inference. Full decode, duration, source/audio checks and sampled scene/transition
review passed. Original materials and revisions remained intact.

See [the completion audit](studio-completion-audit.md) for the delivered scope and
verification boundaries. Private test media are not approved for public website
or repository publication. The published installer version remains unchanged;
this work is available in the deployed development preview.

## Delivery progress

- Project registry and identity workspace merged to develop in #713/#714.
- Native isolated renderer merged to develop in #715; see
  [its contract and qualification scope](../hyperframes-renderer.md).
- Private materials, immutable revisions, local director/storyboards and their
  editor merged in #716; see [material semantics](../studio-materials.md).
- Typed saved-material export now connects API, worker, private native socket,
  isolated full-HD render and Library. Actual fixture qualification includes
  image/video/audio and cleanup; this does not qualify generated reel quality.
- Saved-shot production now reuses actual image and segmented-video Tasks/Runs,
  with model defaults/overrides, frozen references, earlier takes and whole-shot
  Stop; the storyboard previews actual Library outputs on desktop/mobile.
- Completed-PCM soundtrack assembly now extends timing for complete narration,
  ducks/fades a covering score and publishes canonical PCM plus an immutable
  measured edit; synthetic integration tests are not generated-audio acceptance.
- Durable soundtrack production now composes real speech/music child executors,
  measured score coverage and the PCM mix; desktop/mobile exposes actual takes,
  model/reference choices, Stop and measured-version application. Long first
  utterances retain their complete narration while a bounded derived voice sample
  supports later cues. Fake generators/PCM and fixture browser checks qualify
  orchestration, not newly generated voice/music quality.
- Export UI now freezes the same selected takes shown in the storyboard, uses
  complete measured audio and shows actual MP4s, earlier versions, download,
  progress and Stop. Private source/type/ownership tests and fixture playback
  qualify the UI; missing native readiness is displayed as unavailable.
- Existing local renderer activation is exposed in the export workspace through
  private queued setup Runs, with actual Unix-socket/worker activation verified.
  This does not install a missing renderer or qualify new generated films.
- Whole-material production now coordinates measured sound, individual shots
  and export using durable dependencies and owned child Tasks. Stop forwards to
  those children, and continuation reuses complete takes/sound and spoken cues.
  Fake generators qualify the chain, not real complete-film quality.
- Remaining: fresh renderer installation, full-material production qualification,
  actual native portrait-footage qualification,
  assistant tools/project inference, avatar insertion and complete branded
  publication-quality acceptance. The overall goal remains active.

### Complete-material production

A single queued production coordinates existing audio, shot and export Tasks.
Narration and its measured edit precede generated footage, so video covers actual
speech rather than an estimated script length. Existing video Tasks retain their
own segment plans; Studio records immutable owned child-task links and forwards
whole-production Stop only along those verified links. Completed reusable sources
are never canceled. SQL-only coordination steps use durable dependencies, claim
fences and transactional publication; no inference executes in a handler.

Freeze the source revision, explicit takes, actual existing take observations and
model choices. A new attempt may reuse verified complete results from a finished
owned production with the identical request. Missing, replaced or trashed sources
are not success. Earlier completed audio/visual artifacts remain inspectable after
a failed attempt. Final status requires the actual complete exported MP4, not a
successful planning step. Private API/worker tests must cover measured timing,
multiple independent video Tasks, reuse, Stop, ownership and stale claims before
newly generated professional-film qualification and deployment.


## Conversation production bridge (in development, 2026-11-11)

The existing LlamaIndex ReAct controller interprets a complete edited material as
`studio_material`, distinct from a raw clip, a written script or a Git project.
Its frozen intent selects an owner-scoped creative-project alias or standalone
material, format/aspect, duration and narration/music/silence. Ambiguous brands
require clarification. Local planning receives only a bounded current-account
catalog; external providers receive no private creative-project catalog or
Studio execution affordance. Follow-ups retain stable aliases, not row positions.

One composed `studio.produce` tool uses the same material, local director and
whole-film production services as Studio. The call supplies editorial instruction,
title and captured media aliases; it cannot replace the frozen project/options
or grant paths, commands, credentials or model-installation permissions. The
project identity snapshot survives later edits, while access and archive status
remain checked. HTTP only captures intent/enqueues ordinary Runs.

The durable wrapper publishes a planning Task, then the ordinary full-production
Task. Waiting releases the worker slot; recovery replays only atomic queue
publication. Stop follows a closed owner-bound registry and existing production
cancellation, retaining shared runtime consumers. The controller observes one
composed leaf and only its complete final MP4, not hundreds of internal cues or
segments. A storyboard or raw clip cannot fulfill the Studio outcome; different
requested brands/options are accounted for by their original outcome index.

Qualification requires real ReAct/worker fake-media tests for privacy, frozen
identity, all four audio policies, final-output barriers, Stop and stale-lease
recovery; then actual local-model direction and complete-film visual/audio QA.
A passing synthetic film does not prove generated quality or complete this goal.


## Shared planned visuals and requested timing (2026-11-11)

Real assistant qualification selected correct brands/aspects/audio and delivered
MP4s, but a request for one source image across an eight-second material produced
multiple independent images and twelve/sixteen-second films. These are failed
prompt constraints despite successful Runs. Add an explicit typed earlier-scene
visual reference: later beats share the selected/generated source while retaining
their own framing, text, narration, motion and video trim. The reference must
resolve backward to real image/video/Library media, never graphics, future IDs,
paths or model-generated artifact identities. Unique source shots alone generate
takes; render bindings resolve the same frozen artifact for all uses. Video
coverage includes every use. Editing/moving scenes must retain reference identity
or reject the operation before it can silently select another source.

Fit newly directed timing to the requested total frame budget deterministically,
using scene timing as relative beat weights and preserving the one-second minimum
and ninety-second per-scene bound. Insufficient time requires a corrected plan,
not dropping beats. Manually saved timings stay explicit. Measured narration may
extend the edit later without cutting words; show requested and actual durations.
A model's prose describing "the same picture" is not source reuse, and arithmetic
mistakes must not change the user's selected output length.

## Director contention repair (2026-11-11)

A real Studio assistant qualification interrupted its director with “Lease
expired and the owned process is not running”. The worker remained alive and
logged SQLite contention. A short database error escaped the director, abandoned
its in-memory inference and ended the heartbeat; later recovery correctly found
no native process for this container-side planner and interrupted the stale Run.
Extending leases or replaying whole media generation would hide the failure.

Reuse the controller's tested claim-fenced database retry primitive as a shared
Run helper. The director retries only database phases: initialization, provider
binding before network I/O, stream cancellation polls, audit writes and final
revision publication. Keep the same in-flight stream and parsed storyboard;
never repeat inference or generated media on a database retry. Capture original
claim/deadline once, recheck cancellation/ownership after every rollback, release
transactions before awaiting the provider, and retain the ordinary heartbeat.
Unknown database errors remain errors. Historical interrupted Runs stay unchanged.
Regression checks cover transient SQLite codes, binding and publication without
duplicate inference/revisions, and Stop or claim replacement during backoff.

## Native portrait footage candidate (2026-11-11)

The Studio canvas supports portrait, but the bounded/managed Wan recipe currently
forces landscape footage. Native portrait must generate 704×1280, not crop a
1280×704 scene into a narrow strip. Admit only the transposed existing geometry
with the same pixel/frame/step bounds, 11 GiB memory scope and process ownership.
Advertise supported resolutions in native memory-profile metadata; a control
plane connected to an older Runner must reject unsupported portrait generation
before dispatch. Keep legacy landscape receipts and defaults unchanged.

Studio uses its frozen aspect for generated shots. Video workspace format choice
must remain editable for an engine that advertises portrait; unsupported square
choices cannot silently enter the bounded profile. Continuation keeps the exact
width/height and existing checkpoint validation. Qualification needs API/native
validation, managed and configured profiles, continuation/Stop/recovery checks,
format UI and a real owned portrait generation with complete decoding and visual
review. Equal pixel count is a budget bound, not proof of actual quality or GPU
inference success. No model downloads or changes to external runtimes are needed.


### Actual portrait qualification — 2026-11-12

The ordinary owned media queue generated a four-second 704×1280 lighthouse film
through two native Wan windows (81 and 17 frames), twenty sampling steps each,
and the existing single-frame APG continuation. The final file contains exactly
96 frames at 24 fps. Both raw windows and the composed MP4 passed complete
decoding, canonical ownership/content checks and native process completion.
Actual systemd scopes for both windows confirmed 11 GiB RAM and zero swap.
Sampled frames before and after the join retained the full vertical composition
and coherent lighthouse geometry. Media and inspection records remain private.
This qualification covers the short two-window flow; long-film quality, fresh
engine installation and avatar postproduction remain delivery requirements.

The actual conversation checks also now pass for two different project styles:
an eight-second widescreen silent presentation and an eight-second portrait
music reel. Each uses one real generated image shared across multiple scenes;
both full files decoded and retained the selected brand, aspect and audio policy.
The earlier interrupted planning and timing/source failures remain recorded.

## Longer footage delivery

Extend continuous/shot-sequence source production to five minutes within the
existing 7,500-frame, 256-segment native timeline. Studio keeps individual
editorial beats at ninety seconds and uses the complete shared-source trim window.
The UI, typed chat tool and legacy request adapter must agree on the same limit.
New long-workflow deadlines must cover deliberate generation; individual native
process deadlines, Stop, leases and recovery remain bounded and unchanged.

A longer queue must not hide its final film behind the first forty rows or fail
because internal segment/checkpoint artifacts exhaust a conversation's result
limit. Project user-visible artifacts before applying output bounds; retain
bounded recent activity plus the explicit child anchor. Full stage history stays
in Runs and the media job. Keep canonical owner/conversation checks and finite
graph bounds. Persistent-agent definitions retain their independent four-hour
maximum; the longer operator workflow budget does not grant agents more runtime.
Test complete queue coverage, whole-Task Stop, receipt compatibility,
final result projection and account isolation. Short GPU continuation evidence
qualifies the primitive; it does not claim a real five-minute film was generated.

## Presenter and avatar postproduction delivery

Preserve the existing film as a versioned input. First add a typed presenter-video
layer to the existing composition contract and renderer, with an owned Library
video, bounded placement/size and explicit timing. Keep source hashes, ownership,
canonical paths, duration/trim/decode budgets and parent-artifact lineage. Optional
fields must omit their unused value so existing frozen requests remain valid.
The presenter follows the whole film timeline rather than restarting at each
scene. Layout reserves readable space for copy; a selected presenter must not
silently cover titles or replace requested footage.

The first editor slice selects an already completed presenter clip and retains
the film soundtrack. Its controls explain the need for matching narration.
Follow with ordinary queued postproduction from a captured presenter image and
the actual measured narration: build a clean narration stem from approved cues
and pauses, then reuse the existing Sonic whole-recording Task. Compose its timed
video over the film with the original mastered soundtrack, retaining a single
voice. A speech-and-music mix is not the clean narration source. Preserve complete
spoken passages and account for 25 fps avatar versus 30 fps Studio timing.

The semantic assistant must capture presenter intent and approved image/result
aliases, retaining the project's identity. Use the existing Task/Run/Events/
Artifacts and closed child registry for generation, Stop and recovery. No new
command endpoint or generated HTML. Missing source/model permissions and readiness
remain explicit. Keep the new renderer recipe and actual image verified before
switching a live station; old completed films remain available.

Qualification includes schema/hash compatibility, source ownership and changes,
short/invalid clips, whole-timeline alignment, readable portrait/landscape layouts,
audio kept once, Stop/recovery and a real complete generated film with presenter.
The short Library-layer slice alone does not finish automatic avatar delivery or
the overall publication-quality objective.


### Clean narration and long presenter timeline

A presenter workflow must consume the approved measured narration cues, not
transcribe/regenerate the script or feed the music mix into lip synchronization.
Queue a bounded CPU narration-preparation Run anchored to a successful soundtrack
and its exact measured revision. Reuse the existing streaming PCM edit so the
200-ms cue lead-ins, complete utterances and scene pauses match the final mix.
Preserve the original mastered soundtrack as the only final audio.

Publish a clean 48-kHz stereo stem and contiguous owned speech parts of at most
sixty seconds, the current single-Run Sonic input bound. Prefer existing scene
boundaries in the latter half of a part; otherwise retain exact contiguous audio.
Keep all source samples. Only a final shorter-than-0.68-second part may receive
silent input padding for the native minimum; its actual editorial interval stays
unchanged. Do not impose a sixty-second film limit. The complete native render
budget still allows ten minutes. All intermediate artifacts retain provenance
and remain inspectable through Runs without crowding the user's final results.

The subsequent coordinator queues one existing Sonic whole-recording Run per
part, with the same frozen presenter/model and closed child ownership. A typed
presenter sequence uses each complete result on its own exact editorial interval;
25-fps source rounding cannot shift the 30-fps story. Do not restart the face at
ordinary scene changes. Stop/recovery/continuation must preserve completed parts
and never replay an uncertain native launch. Expose automatic presenter selection
in the production editor and semantic assistant only after that complete
coordination path is qualified. Real generated-film acceptance remains required.

The clean-narration primitive is now implemented as an ordinary CPU Run. Actual
qualification used the existing four-cue 17.2-second generated film: its clean
stem retained exactly 825,600 stereo samples at 48 kHz, with complete source/hash
verification and exact reconstruction from its speech parts. The test used a
private disposable database copy and no new inference; the copied database was
removed afterward. Temporary-database tests additionally cover more than 120
seconds, a tiny padded tail, account isolation, changed sources, Stop/claim loss,
expiry, SQLite publication contention and safe pure-CPU recovery. This is not
avatar qualification; the automatic coordinator is described below and full
real presenter-film acceptance remains outstanding.

The renderer now also accepts a typed contiguous presenter sequence: up to 32
complete video sources on exact 30-fps editorial intervals. Each source retains
its own trim; 25-fps avatar frame rounding never shifts later intervals. The new
capability is explicitly advertised, so an older ready engine cannot accept an
unsupported sequence. Legacy single-clip serialization stays unchanged.

Actual CPU qualification used two intervals across a fractional 25/30-fps join
inside a six-second portrait film, with approved existing presenter footage and
calibration audio. Complete decoding, strict Hyperframes lint, reserved layout,
continuous interval coverage, single soundtrack and owned cleanup passed. Initial
qualification caught insufficient time-string precision and an impermissible
GSAP clip-visibility override; both were corrected without relaxing checks.
This proves the composition primitive, not new Sonic generation, long-avatar
continuity or complete narration-aligned film quality.

### Automatic presenter coordination (development)

The existing whole-film coordinator now accepts an optional portrait, installed
Sonic model and finite placement. It freezes source/model observations, obtains
the measured narration through the CPU step, and normalizes a separate bounded
PNG from a complete PNG/JPEG/WebP original. Each contiguous speech part uses one
normal whole-recording avatar Task with the same portrait and no second voice
normalization. The final muted sequence retains exact editorial durations and
the original mastered soundtrack.

The production editor exposes portrait preview/removal, installed model choice,
position and actual readiness. The ReAct tool resolves an explicitly supplied
presenter image alias separately from story footage; it shares the existing
project/format/audio selection and returns the finished film. No person-specific
prompt routing or separate execution engine is introduced.

Temporary-database/fake-executor checks cover a complete film, a 135-second
three-part timeline, WebP normalization without original changes, reuse after a
failed export, Stop, stale coordinator recovery, source/account boundaries,
forged internal provenance and refusal to replay an uncertain native process.
UI tests cover model/portrait/placement submission and unavailable-model recovery.
These checks qualify coordination only. Before closing this stage, build and
probe the exact application image, review/merge, deploy preserving station data,
activate the qualified sequence renderer and generate a complete real film with
its measured narration and actual Sonic presenter. Longer-film visual acceptance
and fresh renderer installation remain required for the overall goal.


### Actual generated presenter baseline and first-use setup

The 17.2-second, four-cue generated film now has an actual newly generated Sonic
presenter from the supplied approved portrait. Studio reused the completed speech,
music and visual takes, prepared 825,600 clean narration samples, then produced
a full 516-frame/30-fps final film. Complete decode/source checks passed. Its
one AAC audio stream correlates 0.9996 with the frozen mastered mix, with an RMS
ratio of 0.9965, confirming that the presenter did not duplicate the soundtrack.
Six sampled moments retained coherent identity and reserved readable story space.
Full audiovisual review, longer-film acceptance and long-avatar part continuity
remain separate gates. No private QA film was published to the repository/site.

The [first-use renderer workflow](studio-renderer-setup.md) also completed actual
installation and Stop through the ordinary API/worker/UDS setup path; its new
engine passed a full-HD export. Its preserving deployment passed with the existing
station data, search service and port bindings retained. This closes the missing
renderer installation path. Actual simultaneous worker/Runner crash recovery
retained the same Run and original helper and completed without duplicate stages.
The whole Creative Studio publication-quality objective stays active.


### Cold audio verification repair — 2026-11-12

The actual 75-second educational-film request selected the intended brand project,
landscape format and narration/music through the local assistant. Its director
saved the storyboard, but production failed before speech dispatch: Fish returned
`available=false, readiness=checking` while verifying installed files after a
Runner restart, and the coordinator treated the ordinary HTTP 409 as permanent.
This is a readiness-publication race, not evidence of a failed speech inference.

Speech/music publishers now distinguish explicit pending native verification with
a typed HTTP-409-compatible exception. The existing audio coordinator rolls back
that publication attempt, reacquires the Task/claim fence, and defers the same Run
using ordinary durable resource backoff. It starts no replacement planning or
native workload while waiting. Completed cues remain attached; unknown, missing
or changed configurations still fail. Verification is bounded to five minutes per
stage and remains subject to Task Stop, worker recovery and the production's
original deadline. No schema, public endpoint or execution boundary changes.

Qualification requires pending-to-ready publication without duplicated cues or
score, backoff, timeout, permanent-unavailable failure and concurrent Stop/claim
fences, plus relevant speech/music and production regression suites. After reviewed
deployment, continue the saved real storyboard through ordinary production reuse
and inspect the complete longer film; the original failure remains in history.
The final publication-quality objective remains active.


### Explicit spoken-script length — 2026-11-12

The resumed long-film qualification completed all six Fish cues, its instrumental
score and PCM mix. The cold verification repair passed with the same coordinator
waiting and then dispatching once. A separate editorial defect is now explicit:
the requested 170–190 spoken words survived only in prose; the director saved a
127-word script. The first completed cue lasts 8.59 seconds inside a 16.03-second
scene. This does not yet establish the final edit's quality, but explains why
count/duration fidelity needs validation before expensive generation.

Optional `StudioOptions.narration_words` captures minimum and/or maximum spoken
word limits. The assistant extracts these semantically only when requested;
seconds and captions never create a word limit. They belong to the material and
its immutable versions, not to brand defaults or model execution settings. Missing
limits serialize exactly as before, preserving sparse voiceovers and legacy
request identities. A script count includes only whitespace-delimited spoken
words/numbers; punctuation-only tokens, titles and direction do not contribute.

The director checks the actual script against frozen bounds before publication.
Its existing one-correction pass reports the measured count and unmet bound;
a second failure retains the old version and starts no media. Manual version
publication uses the same validator. Material creation exposes optional bounds;
the editor displays the live spoken count/target and lets the user explicitly
remove the limit without discarding edits. A limit is never satisfied by truncating
speech, inventing filler in postproduction or changing the requested duration.

Qualification covers range validation, exact/one-sided limits, silent-policy
conflicts, unchanged legacy JSON, semantic intent through complete fake production,
model correction/failure before media, manual save, UI edits/removal and full
existing Studio regressions. Real semantic extraction and the longer completed
film's pacing remain actual-model/visual acceptance gates after reviewed deployment.


### Brand direction must not become lettering

The same actual long-film run produced a photograph containing palette swatches
and printed hexadecimal labels from its shot brief. The model received literal
CSS codes alongside the brand direction; a general no-lettering sentence did not
prevent this. That image is evidence of an editorial failure, not an accepted
publication sample.

Studio shot preparation now translates three/six-digit CSS color literals into
standard named visual colors and explicitly excludes palette/sample graphics.
Hue/tone proximity selects the name; a generated photograph cannot guarantee exact
RGB values under changing lighting. Frozen project colors remain unchanged and
are still used exactly for composited typography/backgrounds. The director also
receives a clear separation between physical visual color direction and numeric
design tokens. This syntax translation applies only to Studio media prompts,
never to user-intent routing, arbitrary ordinary Image requests, references,
original project records or completed artifacts.

Pure/publisher tests cover multiple palettes, existing saved shot direction,
untouched source/brand records and no speech/caption leakage. Actual generation
must still be inspected after deployment; removing a literal token alone does not
prove absence of all unwanted lettering or establish publication quality.


### Compound planning correction — 2026-11-12

The real corrected request selected the right brand, landscape, voice/music and
170–190-word limits. Its first director response nevertheless combined multiple
independent defects: oversized framing fields, a 248-word script, five rather
than six requested scenes, and a twenty-second Library beat for a six-second
owned clip. The first validation stopped at the framing schema errors. The one
remaining model correction fixed those fields but retained 248 words and failed.
No media was dispatched for that invalid plan; a successful controller reply did
not constitute a delivered film. The model's poor proposal remains rejected.

The director now collects independent script/audio/source/schema defects into
one bounded correction report. It includes measured scene/visual/script counts,
compact field paths without echoing invalid input, and available Library video
windows. A framing failure can no longer hide the spoken-word bound. A completed
video receipt may supply a finite typed duration to the local planner; unknown or
unverified timing stays unknown. These are descriptive observations, not native
execution authority. Owned source hashes, reference/account boundaries and final
native media inspection remain unchanged. The original two-attempt limit and
valid-publication barrier remain in place.

Qualification must reproduce the actual framing-plus-word-limit failure and
repair it in the single remaining attempt; check post-fit and malformed-proposal
source windows, policy/source errors, bad raw shapes, timing provenance and the
existing director/production suites. Then repeat actual local-model planning
with the preserved complete six-second clip. Inspect requested scene/visual
counts as well as word/time bounds; the complete film and publication-quality
acceptance are still open and must not be inferred from this diagnostic repair.

The conversation wrapper also preserves the first owned underlying stage failure
instead of replacing it with an opaque generic stage error. Owner checks precede
that projection; no partial artifact becomes a completed film. The public API,
permissions, database schema and valid legacy request identities do not change.

### Focused narration correction and closed planning budgets — 2026-11-12

The next real attempt preserved the six-scene visual structure and corrected the
six-second Library window, but still exceeded the frozen 170–190-word script
range. ReAct then paraphrased the same request into additional whole-workflow
attempts; none delivered a film. This is not a media-quality qualification.

Once schema, audio policy, source ownership and fitted source windows validate,
a word-limit-only failure now enters a speech-only editor on the same owned
planning Run. The selected local model returns indexed spoken lines, not another
storyboard. Application code copies only narration fields. Scene order, visuals,
references, typography, delivery, source trims and intentional silent beats stay
unchanged. Measured global word limits remain mandatory at publication. Advisory
per-scene pacing leaves room for short moving beats; actual TTS samples and native
source inspection still determine whether the edit fits. No string truncation,
filled-in facts or relaxed user requirements are used to make validation pass.

There are at most two complete outline proposals and two focused script proposals
under the original Run deadline, claim fence and Stop checks. Every request and
response is retained for inspection. Exhaustion is a server-recorded planning
outcome, not a model-selected retry permission: the assistant cannot create more
materials for that same frozen outcome in the same user turn by paraphrasing it.
Other requested materials and a subsequent user instruction remain available.
Runtime readiness failures without an exhausted planning budget keep their normal
recovery semantics. Missing films remain missing, with their actual failure and
retained draft; the wrapper never substitutes a partial image or storyboard.

Regression coverage must include visual immutability, strict indices, silent-beat
preservation, exact/one-sided word ranges, one focused correction, Stop during
editing, preservation of prior revisions, no duplicate whole-workflow retries,
and independent outcomes. The actual longer production and publication-quality
acceptance remain open until verified after deployment.

### Semantic interpretation correction evidence — 2026-11-12

The next actual film request failed before Studio dispatch: both bounded semantic
intent candidates were rejected. No storyboard/media existed for that turn. The
old generic error retained neither candidate nor validation details, so its exact
schema/alias defect cannot be reconstructed from that Run. Do not describe this
as a demonstrated narration-edit failure or claim a known specific model defect.

The interpreter now retains at most two bounded structured candidates in the
same private owned planning Run. Rejection events expose only bounded schema
paths/messages, excluding Pydantic input values. The one correction includes the
actual rejected candidate followed by its measured error and the unchanged
current instruction, after reference history. It cannot silently repair intent,
change permissions, freeze an invalid outcome or dispatch a tool. A final failure
keeps the precise diagnostic. ReAct scratchpad thoughts are not captured by this
intent-only evidence. Existing claim, deadline, Stop and account fences apply to
every evidence write and publication. Actual successful interpretation and the
complete longer film still require a fresh ordinary request after deployment.

### Nonverbal generated visuals — actual qualification finding, 2026-11-12

The next actual request successfully corrected semantic interpretation (an
oversized description) and revised only its narration from 230 to 179 words.
All six visual scenes, sources and other fields were preserved; complete speech,
music and mastering then succeeded. Measured narration extended the requested
75-second edit to 95.633 seconds. Report that actual duration, not the earlier
storyboard estimate. The finished film and its publication quality are still open.

The first new photograph had no palette bars or hexadecimal labels and a coherent
editorial composition, but contained pseudo-text on its display. Its actual
visual brief explicitly requested an interface showing a text prompt. The previous
director rule prohibited generated titles; the general no-lettering suffix then
conflicted with that specific requested writing. This is an instruction-boundary
quality defect, not evidence that a particular subject needs special-case code.

Director guidance now separates all writing from generated visuals, including
incidental/tiny/illegible interface or document copy. All intended wording belongs
in the renderer's existing scene text fields. Generated surfaces are described
through nonverbal shapes/materials/light. The shared image/video shot suffix
reinforces the same policy. No subject matching, prose deletion, image repainting,
new tool, changed source or inference parameter is introduced. Existing ordinary
Images requests and approved Library sources retain their original semantics.

This prompt-direction change remains a candidate until actual planning and new
visual generation verify the separation. Preserve useful completed film assets;
do not rerun or stop the whole production merely to repair one image. A good
composition or absence of one former defect cannot establish publication quality.

The completed 95.633-second film passed all 2,869 decoded full-HD frames and
single-track audio correlation checks. A local CPU transcript had three word
edits across 179 expected words. These checks do not constitute full subjective
publication acceptance. Sampled final layouts also exposed cropped edge pictograms
and the baked-in label of an illustration in a near-square panel. The existing
`media_fit` choice remains authoritative: director guidance now explicitly chooses
`contain` for complete informational/edge content and reserves `cover` for
intentional crop-safe photography. There is no runtime content classifier or
forced change to existing revisions; real layout/generation qualification remains
required. Preserve the complete baseline film for comparison.

Actual candidate qualification now passes ordinary local planning with the same
original brief, selected model and inspected six-second source, without a
prefilled storyboard or correction feedback. It produced six scenes, 176 spoken
words and exactly 2,250 frames. Source-aware fitting retained the six-second
Library shot and four-second generated-video beat; elastic stills absorbed the
remaining time. Three complete informational illustrations selected `contain`.
The first new photograph was generated through the ordinary saved-shot/image
workflow with the same installed LUSTIFY definition. Inspection found a coherent
blue/cream workstation photograph with a clean dark display and no former
pseudo-writing. The exact deployed candidate passed its packaged API/migration
and source-fitting probes. These are measured planning and visual-generation
results, not a claim that the new plan has already been fully produced or that
every future image is guaranteed free of lettering. The original complete film,
soundtrack and successful footage remain preserved for focused postproduction.

### Editable composition — 2026-11-12

The saved-shot editor now exposes the renderer's existing layout, `media_fit`,
`media_motion` and video `media_start_seconds` fields. Whole-visual fitting with
no added movement preserves informational edge content; the UI explains that
zooming/panning can still crop and that the whole scene must fit in its source
clip. Video controls also work for shared and Library sources. Graphics do not
offer inapplicable media controls or a full-bleed layout. No new source, inference
parameter, execution permission or backend contract is introduced.

Edits retain the existing unsaved-change/export guards and save as a new
immutable revision. Original sources, shared-source references, narration and
timings remain unless explicitly edited. Local frontend qualification covers
46 Studio cases, lint, typecheck and production build. Compiled desktop/mobile
checks against an isolated real accounts/API instance confirmed whole-visual
fitting, motion/layout persistence, original-revision/source preservation and no
new generation Run. The mobile composition controls have no horizontal overflow.
This editor qualification does not establish a film's publication quality.


## Narration acceptance and conversation revisions — 2026-11-12

The owner accepted the complete 75-second educational film's narration:
“Narracja jest dobra w całym filmie.” This closes full-film narration pace,
expression and continuity review; it is not blanket visual/publication approval.
The private acceptance receipt retains the actual film and source checks.

The next execution gap is follow-up editing: preserve the editable source version
and reuse its completed media instead of starting a new unrelated production.
See [conversation revision contract](studio-conversation-revisions.md) for source
scope, explicit replacement, exact audio/presenter reuse and qualification gates.
Do not regenerate or retune the accepted narration merely to exercise this path.
