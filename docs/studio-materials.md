# Studio materials and editorial versions

Studio materials are independent of software Projects and Git. A material has
an optional creative project, a brief and format/aspect/length/audio preferences.
Its immutable editorial revisions retain the exact brief, preferences, identity
snapshot, source observations and parent version. Archiving preserves history;
optimistic edits cannot overwrite another browser's newer work. Creation and
revision receipts are idempotent. Migration 0047 adds separate collections and
does not rebuild existing creative sessions or change their generators.

The account policy treats materials as private roots and revisions as inherited
records through their material and optional source Run. A foreign project,
revision, source Artifact or Run cannot be attached. Administrator inspection
remains explicitly read-only. Library sources are live image/MP4 artifacts,
canonical below app storage, hash-observed and checked again in the worker.

`/studio` and each project list materials as well as existing creative assets.
A material opens a storyboard workspace: numbered shots, their narrative
purpose, visual direction/framing, on-screen text, narration and sound direction.
Scene edits/reordering create a new version. Earlier versions remain selectable;
unsaved edits block replanning/version switching. Materials can be archived and
restored. Desktop gives the storyboard the main area; mobile presents a saved
storyboard before the refinement controls.

The director is a normal queued `studio.plan` Task/Run, executed by
`studio_director` through the selected local provider. Managed llama.cpp uses
existing model preparation, dependencies and resource ownership. No inference
runs in an HTTP handler. Streaming has cancellation, a twenty-minute absolute
budget, a bounded response and one schema correction. Success stores a JSON
Artifact, a revision and structured events. Failure/Stop retains existing
versions and never publishes a partial plan as generated media.

The structured storyboard separates narrative intent from runtime settings.
Each shot chooses planned image/video, an existing Library source or deliberate
editorial graphics. It includes framing, motion, timing and actual spoken words.
No shell, HTML, tools, arbitrary source paths or URLs are executable input.
Requested voice/music policy cannot silently disappear. Sources can only come
from the supplied owner-scoped catalog. Source descriptions are not claimed as
visual inspection; model output is a plan, not evidence that assets were made.

The typed export bridge now accepts a saved revision with actual owned media
bindings and a complete soundtrack. It enqueues a normal `motion_render` Run,
reserves 4352 MiB and dispatches through the private Runner socket. A planned
video shot requires real video; missing footage cannot become a text template.
The soundtrack must contain exactly the saved frame coverage in 48-kHz stereo
PCM. Source hashes and the frozen storyboard are rechecked before dispatch and
Library publication. The export retains its revision, identity and source lineage.

A lost launch reply leads to observation, never replay. A missing native record
must be cancellation-fenced before release; unreachable or unconfirmed container
cleanup retains reservations for inspection. The control-plane image includes
only the pure composition contract, never native launchers or Docker authority.

Private actual API/worker/Unix-socket qualification on 2026-11-11 produced a
1080×1920, 30-fps, 180-frame MP4 with real image/video sources and calibration
audio, adopted into the private Library with verified cleanup. Fake tests also
cover ownership, changed sources, lost replies and uncertain cleanup. This is
integration evidence, not a professional complete reel or generated narration.

Saved image/video shots now enqueue their existing generators from the storyboard.
Each take has its own ordinary Task and inspectable Runs, with frozen revision,
identity, direction and reference observations. Images use the account's
per-operation default or an explicit compatible model; reference shots use
Recompose. Generated footage uses the existing real continuation/assembly graph
for the full requested coverage, not a still or repeated short clip. A retry of
the same receipt keeps its identity/seed; a new take changes supported seeds.
Concurrent duplicate active work is refused. Stop applies to all stages of that
shot, preserving other materials and earlier takes.

The storyboard shows actual image/video previews, take comparison, Library links,
progress and model choices on desktop/mobile. Unsaved edits cannot launch media
against the saved version. Archived materials retain their results. Existing
video runtime limits remain explicit: at most sixty seconds per generated shot,
one optional first-frame reference and native widescreen footage. The final
portrait composition does not imply native portrait inference. Full-image
prompts retain the supplied generic subject/framing/brand direction, without
person-specific presets. Runtime video prompts have their existing 2000-character
budget; over-budget directions are rejected rather than silently truncated.

Private actual browser/API checks exercised generation enqueue/Stop, existing
approved SFW fixture previews/take comparison and desktop/mobile layout. This is
not a claim that new image/video inference was performed in those UI checks.

A queued soundtrack assembly API now measures completed owned PCM cues before
editing. It preserves every spoken sample, extends scenes where necessary and
saves the measured edit as a new immutable revision. The score must cover that
whole edit; short music is rejected, never looped invisibly. A streaming local
worker mix applies smooth cue-level music ducking, opening/closing fades and one
global peak adjustment. Two disk-backed streaming passes avoid source-sized
arrays and per-block pumping. Output is exact 48-kHz stereo PCM, with source
lineage, measured timing and mix settings in Library. No external tool/network,
GPU, executable filter string or extra native privilege is involved.

Mixing checks sources again before publication and fences results by worker
claim and Task Stop. A failed/canceled mix keeps earlier revisions and deletes
its private scratch files. Synthetic PCM integration tests cover resampling,
complete narration, voice/music policy, peak control, ducking, privacy and Stop;
they do not qualify generated voices or subjective final soundtrack quality.

The saved storyboard now starts a durable speech → measured score → final mix
production. Each spoken cue uses the existing local speech executor; the first
generated narrator becomes the reference for later cues, or the chosen Library
recording remains authoritative. Structured director delivery selects the declared
local expression/pace controls. Music follows the single saved Music direction,
with optional runtime/level choices. It is generated only after actual utterance
measurement, and the final mix retains all completed narration. No model inference
runs in the enqueue-only coordinator or HTTP request.

A first passage longer than the existing sixty-second voice-reference limit is
kept in full. A separate CPU Run prepares a lossless fifteen-second reference for
later speech, with frozen source/parent lineage, bounded streaming buffers and
Stop/claim fences. The complete original cue remains the narration source. A
selected Library narrator must already satisfy the existing 0.1–60s/20-MiB speech
contract, checked before queueing. This is voice consistency, not word truncation
or an additional voice model.

Only SQL-only coordinator publication may safely requeue after an expired lease;
actual voice/music/reference generation retains its ordinary execution/recovery
contract. Whole-production Stop preserves completed cues. The UI shows real
progress, take comparison, playable results, model/reference choices and an
explicit action to apply the immutable measured edit. That timing-only revision
retains its verified actual visual takes; rewritten storyboards do not inherit
unrelated footage. Short existing footage is flagged for a longer take. Failed
production retains completed artifacts but does not yet resume them in a new
production request.

Fake-generator/real-PCM integration covers the complete durable chain, private
status, Stop, SQL-only recovery, narrator continuity, long-cue reference sampling
and unchanged full narration. Actual browser/API checks play a calibration WAV,
apply measured timing while retaining both existing approved visual fixtures, and
inspect desktop/mobile settings with no overflow. These checks performed no new
speech/music inference and do not qualify subjective audio quality.

The export workspace shares selected takes with shot previews and freezes those
exact choices in the existing typed render request. Missing footage, short known
clips, missing measured audio, unsaved edits, active generation and unavailable
renderer readiness gate submission. It never silently replaces a selected deleted
take or substitutes an image for video. An advanced option accepts an owned final
WAV; the server still enforces exact complete 48-kHz stereo coverage. The private
export history exposes only live complete MP4s from successful render Runs.
Earlier versions, playback, authenticated downloads and Run inspection remain
available even when a new export cannot run. Stop uses existing owned Run
cancellation. No new executor or native privilege is added by this UI.

Private actual browser qualification plays the previously qualified six-second
1080×1920 composition with calibration audio, tests authenticated range/download
and inspects desktop/mobile layout and expanded options. Its real unavailable
renderer remains unavailable. This is UI/fixture evidence, not new model
inference, a fresh render, or professional-film acceptance.

Full-material automation, guided renderer preparation and Chat project inference
remain in development. Final publication-quality acceptance requires a complete newly
generated voiced/scored reel and educational film with full playback/visual
review, not just a valid storyboard or fixture export.

## Whole-film production

The saved storyboard now has a **Produce film** action. A normal queued
production creates sound and a measured edit before generating footage, then
exports completed selected takes and the full soundtrack. Individual shot,
soundtrack and export controls remain available. The material's original version,
source observations and chosen model settings are retained for inspection.

`POST /api/studio/materials/{id}/produce` accepts a submission UUID, saved revision,
optional selected takes and local generator choices. It performs metadata/readiness
inspection and queues work; inference runs only in existing workers/Host Runner
executors. `GET /{id}/productions` reports the complete owned Task graph and actual
finished MP4. A successful coordination Run alone is not a completed film.

**Stop production** follows verified owned child Tasks, including video segment
plans. **Continue · reuse completed media** starts a new attempt of the frozen
request and preserves complete sound and takes. If speech failed partway through,
completed spoken cues can be reused with the same narrator; modified or unavailable
sources cannot silently enter the next generation. A short implicit video take
can be replaced by longer footage for the measured narration. An explicitly
selected short take needs review instead of silent looping, padding or substitution.

Qualification uses temporary databases and fake image/speech/music/video/export
executors, with the actual PCM mixer and ordinary queue/dependency services.
Desktop/mobile browser checks cover the real account/API and unavailable-export
state. These checks do not qualify a newly generated professional film, portrait
video quality, fresh renderer installation or a production rollout. The complete
Creative Studio delivery goal remains active.


## Unified assistant production

A complete edited reel, presentation or film can be selected semantically by the
existing LlamaIndex ReAct assistant as `studio_material`. The captured intent
contains the creative-project alias (or standalone/clarify), format/aspect,
duration and audio policy. The owner-scoped catalog remains local; no new mode
switch or word-matching router is used. `studio.produce` accepts editorial text,
title and exact supplied media aliases and queues the same local director and
full-production workflow as Studio. The assistant waits for a complete final MP4,
with a link to the material for storyboard/production review. Stop forwards only
to its verified owned planning/production Tasks. Intermediate images, narration
cues and video segments are retained in Library/history but are not substituted
for the requested final film in the conversation.

This bridge is in qualification: synthetic workflow checks establish lifecycle,
privacy and result publication; they do not qualify actual generated quality,
portrait footage or fresh renderer installation.


Captured project names and domains are exact resource aliases as well as opaque
catalog keys. After semantic model selection, the server canonicalizes a unique
advertised name/domain to its frozen key; unknown, partial and shared labels
require clarification. This is resource binding, not a keyword intent router.
When a cold native renderer reports `checking`, the conversation keeps its
completed storyboard and waits using durable admission backoff without a worker
slot. Verification has a two-minute bound; unavailable engines still fail for
inspection, and no media execution is repeated during this metadata wait.


## Publishing volume (development)

New soundtrack Runs freeze the `studio-lufs16-v1` finishing profile. The packaged
PyAV/libav EBU R128 meter measures the complete canonical stereo PCM, applies one
bounded whole-file gain toward -16 LUFS, and protects peaks using a 4× oversampled
limiter. The finished PCM is measured again: the stored report includes actual
before/after loudness, a conservative true-peak bound, gain, target attainment
and exact sample coverage. It does not substitute target values for observations.
Gain is capped at 18 dB; gated audio is not amplified and digital silence stays
zero. The PCM true-peak ceiling is -1.5 dBFS, with a -2 dB limiter setting to leave
resampling/encoding margin. [EBU filter semantics](https://ffmpeg.org/ffmpeg-filters.html#ebur128).

All passes stream bounded blocks through existing CPU worker code, check Stop
and the claim, and publish only after source revalidation. No model, shell,
network operation or native capability is added. Music stays ducked under speech;
music-only output is finished as a complete score instead of remaining at the
low background-bed volume. Each new audio coordinator pins the selected policy;
historical queued coordinators and mixes without that coordinate keep their
original behavior. Existing submission receipts and published files are unchanged.
An explicit typed `mastering_profile: "none"` on the manual mix API retains original
volume. Inspector/Library metadata retains the measured result; the sound panel
claims balanced volume only when the target was actually attained.

Actual-model qualification has also identified two remaining editorial gates:
planned reuse of one image across scenes must share one generated source, and
silent/music-only scene timings must honor the requested complete duration.
Repeatedly generating a described "same image" or accepting a longer storyboard
is not proof of visual continuity or correct timing. These remain active work,
separate from DSP qualification.
