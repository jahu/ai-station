# Synchronized scene sound (NR-07), then timeline editing (NR-08)

Owner request: describe the sound of a film and obtain actual synchronized local
sound effects/ambience, with a later editable multitrack film. Speech, music and
effects remain separate stems and capabilities. This is not satisfied by adding
music to a silent video or by exposing an unqualified model selector.

## Selected candidate and current evidence

[MMAudio](https://github.com/hkchengrex/MMAudio) generates audio conditioned on
video and text. Source is pinned for qualification at
`974010a026c731054592d8f777218bd9d85a6c24` (MIT code); the
[publisher checkpoints](https://huggingface.co/hkchengrex/MMAudio) are separately
CC BY-NC 4.0. The first candidate is `large_44k_v2`, BF16, one discovered CUDA GPU.
Actual local measurements and integrated qualification are recorded below;
readiness requires the configured pinned runtime, not merely a matching filename.

The independently installed, project-owned runtime is separate from Fish,
Chatterbox, the control-plane image and existing user model trees. Public assets
are downloaded at immutable revisions and checked against publisher SHA-256 (LFS)
or Git blob identities (small configuration files). Required inference assets:

- MMAudio flow model, 44-kHz VAE and Synchformer at checkpoint revision
  `eb13a1a98fdbec91753775c57b074ccdfc60587c`.
- CLIP config/weights at `01b771ed0d1395ca5ffdd279897d665ebe00dfd2`.
  The upstream `apple/DFN5B-CLIP-ViT-H-14-384` URL redirects to the `378` name;
  retain the explicitly verified revision and make offline resolution match the
  upstream import. Do not silently follow a new model during execution.
- NVIDIA BigVGAN config/generator at
  `95a9d1dcb12906c03edd938d77b9333d6ded7dfb`.

The upstream demo downloads automatically, has unsafe prompt-derived filenames
and can truncate conditioning duration. Do not invoke it as the public adapter.
Use its inspected inference functions inside a fixed owned wrapper with offline
resolution, UUID-derived paths and independently verified timing. Do not modify
upstream source to make a model fit. Private download/runtime/qualification
records belong under `data/acceptance/synchronized-sound-20261030/`.

## Qualification before activation

Use a neutral short film already owned by QA, plus a repeatable moving-object
fixture with a visible timed action. Check real video+text conditioning, complete
finite PCM, source frame coverage, sample count and actual peak VRAM/RAM.
Compare appropriate prompts (e.g. water, footsteps, wind) without claiming that
successful decoding proves perceptual synchronization. Use a real zero-swap owned
memory scope, and measure the profile before selecting its RAM/VRAM admission
limits. Never evict an external runtime or use CPU weight offload implicitly.
Exercise Stop during model loading/generation, process inspection after lost
acknowledgement and absence of published partial output.

## Shared execution contract

Add a typed `audio.effects` request with an owned video artifact, sound
instructions, negative prompt, bounded sampler settings/seed and GPU selection.
The request accepts no command, graph, model path, URL or arbitrary filter syntax.
An API handler freezes same-owner inputs and enqueues an ordinary Task/Run.
The worker reserves measured resources and dispatches a fixed native operation;
Run parameters freeze source/weight/wrapper observations and timing. Inspection,
leases, absolute deadline, cancellation and retry policy reuse existing services.

Freeze inspected frames, FPS, dimensions, source size/hash and exact timeline.
Start with existing verified app-generated MP4 clips at supported frame rates;
other imports must pass a real inspection Run rather than trust client metadata.
Long films use bounded windows in one owned execution, with explicit planned
window boundaries and continuity policy. Inspect the complete source, sample
conditioning at the model's actual CLIP/Synchformer rates, and bound decoding.
The final window may be padded for model conditioning, but publish precisely the
requested film's sample interval. Record this conversion; never shorten the film
or silently drop its final action. Verify the final sample count against the
source frame count using rational timing.

Publish a reusable WAV effects stem and a linked video-with-sound preview via the
existing typed compositor. Each is an ordinary Artifact with source lineage and
model/prompt/seed/timing provenance. Keep the original silent film. Existing
narration/music must remain available independently; replacement versus mixing
must be explicit. Arbitrary multitrack mixing belongs to NR-08 below.

## User experience and saved work

Add **Sound effects** beside Speech/Music in Audio. The form asks for the film
and what should be heard, with advanced controls collapsed. Show source video,
actual duration, model/local status, measured progress and honest estimates.
Offer **Add sound** from completed video/Library results and preserve the chosen
source when navigating. Reuse MediaInput/MediaResult and ordinary Stop/Run details.
A result exposes the standalone effects track and synchronized preview.

Extend the existing private creative sessions with an `effects` capability,
including a preserving Alembic migration for its database check constraint,
backend builder, frontend types/routes, drafts, feedback and saved variations.
Do not use browser-only history. Agent/assistant integration must use the same
schema/source authority and available-engine checks; no independent execution
architecture. Enable adapters only after permissions, cancellation and recovery
pass. Unconfigured candidates remain unavailable.

## Timeline handoff (NR-08)

Persist owner-scoped timeline projects and append-only revisions, with clips and
independent speech/music/effects tracks. A revision freezes artifact snapshots,
source in/out, timeline start, gain, mute and bounded fades using rational
sample/frame accounting. Trimming/moving/reordering changes a saved manifest,
not source artifacts. Provide drag controls with accessible numeric/keyboard
alternatives, preview waveforms/playhead and explicit render.

The native compositor builds a fixed validated mix/encode operation; callers
never supply FFmpeg graphs/argv. Preview and export follow the same manifest.
Check clipping, audio coverage, FPS/sample timing and cancellation; retain each
render, source lineage and prior revision. NR-07 effects must remain useful as
ordinary stems before the full editor is available.

## Initial local qualification, 2026-10-30

The isolated inference-only Python 3.12 environment uses Torch/torchvision/
torchaudio 2.8/0.23/2.8 with CUDA 12.6, prebuilt PyAV 16.1 and NumPy 2.0.2.
PyAV 14 resolved to a source build requiring host FFmpeg development libraries;
that attempt was rejected and replaced with a prebuilt wheel, without OS changes.
All seven required inference assets passed publisher identity/size verification.

A real video-conditioned, 25-step BF16 sample from a 33-frame/24-FPS neutral
bicycle fixture produced mono 44.1-kHz PCM in 4.40 seconds after 30.52 seconds of
loading. Measured peak allocations were 4834 MiB GPU and 10.26 GiB scoped host
memory under a real 24-GiB/zero-swap bound; all model parameters stayed on the
allocated GPU. The upstream loader shortened conditioning from 1.375 to 1.36s;
the report preserves this observation and the explicit sample adjustment. The
production wrapper must sample/hold the complete inspected video timeline and
record exact final PCM timing, rather than repeat that implicit shortening.
Eight-second maximum-window qualification remains separate. These are standalone
measurements, not an available AI Station SFX adapter or perceptual acceptance.

The pure frame/sample window planner has 21 passing cases across 24/25 FPS,
short tails, overlapping windows, 44.1-kHz half-sample frame boundaries and
five-minute bounds. Absolute endpoints prevent per-window rounding drift; the
future renderer must verify the final output against those same endpoints.

The full-window test also passed: 192 frames at 24 FPS, exact 352800-sample
8-second mono output, 25 steps, 10.25 seconds generation after 35.20 seconds
loading. Peak allocations were 5067 MiB GPU (5238 MiB reserved) and 12.95 GiB
scoped host memory, with GPU-only weights. The upstream helper again shortened
conditioning, this time to 7.96s; exact source frame sampling/hold is required in
the adapter. Final timing correction was explicit and recorded in the private
report, not hidden as model synchronization acceptance.

These measurements support starting qualification of a conservative 8-GiB VRAM /
18-GiB RAM profile. Do not select a 12-GiB host-RAM limit: the eight-second run
actually exceeded it. Actual scoped generation/cancellation/recovery for that
final profile and private API/worker/UI integration still precede availability.
Private reports: `qualification.private.json` and `qualification-eight.private.json`
in the acceptance directory above; both native processes completed successfully.

## Integrated adapter and saved workspace

Audio → **Sound effects** accepts a completed AI Station film from Library,
a description and optional local prompt enhancement. Advanced controls contain
negative sounds, seed, steps, guidance and GPU. **Add sound** on a completed film
stages that exact source. Saved private workspaces retain the request, feedback,
versions, output and task-wide Stop. Each result keeps a separate WAV stem and a
verified MP4 preview; the preview replaces audio only in the new output, leaving
the original intact. Effects are not offered as voice references.

Configure the native Runner with `AI_STATION_MMAUDIO_ENABLED=true` and the
`AI_STATION_MMAUDIO_PYTHON`, `AI_STATION_MMAUDIO_DIR`,
`AI_STATION_MMAUDIO_MODELS` paths. The isolated Python runtime also needs Pydantic
v2 for the typed wrapper. Inference dependencies are pinned in the private freeze
record: Torch/vision/audio 2.8/0.23/2.8 CUDA12.6, OpenCLIP2.32, timm1.0.30,
PyAV16.1 and NumPy2.0.2. The seven published assets are materialized as direct
verified files under the configured model root (`flow.pth`, `vae.pth`, `sync.pth`,
`clip/` and `vocoder/`). Constructors load those exact local files with networking
disabled; inference never follows mutable Hub aliases.

The worker uses **8 GiB VRAM / 18 GiB load RAM**, a 30-minute absolute deadline
and inspect-before-retry recovery. The native request repeats admission and binds
the code/model/wrapper observation. Every conditioning window is exactly eight
seconds: short tails hold their last actual frame. All source frames are decoded
and checked for constant 24/25 FPS timing, dimensions and complete coverage.
Windows share approximately 250ms of the same timeline for an equal-time
crossfade. Their absolute 44.1-kHz PCM endpoints produce the exact film interval,
including fractional-sample frame boundaries. Up to five minutes/1280×704 are
bounded by validation; full five-minute hardware generation has not been run.

Ordinary API → worker → owned native tests generated complete eight-second and
15-second/two-window effects, then verified video previews. Actual loading Stop
inside the final 18-GiB/zero-swap scope released the owned process/GPU reservation
without publishing partial output. These reports are `real-api-r2.private.json`
and `real-long.private.json`. The initial attempt failed before model import due
to a missing wrapper dependency; that environment dependency was installed and
the failure record retained. Standalone measurements above are not substituted
for these integration checks.

Normal fake contracts cover RAM/VRAM admission, strict inputs, changed source,
idempotent dispatch/deadline, lost acknowledgements, account A/B history/files,
local prompt preparation and separate linked outputs. Migration 0040 preserves
populated creative sessions/turns with foreign keys enforced. Compiled private
desktop/mobile checks use a real API, separate worker, typed native adapter,
synthetic GPU inference and real CPU composition. Final release packaging and
production rollout are recorded separately.

The full NR-07/08 scope remains open: per-scene instruction editing, agent/assistant
exposure, perceptual synchronization acceptance and the saved multitrack editor
still require implementation/qualification. An available basic effects generator
is not a claim that the entire release or timeline editor is complete.

## Development deployment, 2026-10-30

PR #524 is reviewed, squash merged to `develop` and deployed on the development
workstation. Final qualification includes 198 affected Python cases across 20
complete families, 59 UI cases across eight families, Python/frontend static
checks, production/development/LAN Compose validation, the application image and
all 229 packaged Python source identities. The packaged fake API/worker/SSE
exercise and compiled private desktop/mobile workflow pass; GPU inference alone
is substituted in that browser test, while preview composition is real.

The production upgrade preserved all 37 existing domain tables across 0039 →
0040, with foreign keys intact and a pre-upgrade backup. The updated native
Runner retained the private access node and existing model observations. Actual
production desktop/mobile readiness/form checks pass; the four Audio tabs use
a readable two-column mobile layout. The trusted QA device was revoked. Private
rollout and source-review evidence is in the acceptance directory above. These
checks do not close the per-scene, perceptual or timeline work listed earlier.


## Scene direction increment

An optional ordered list of at most sixteen non-overlapping cues binds source
start/end frames and a bounded sound description to the inspected film. Outside
those ranges the overall description remains active. The UI accepts seconds
and converts them using that source’s verified frame rate; source changes clear
the old ranges. Drafts/versions retain every cue. There is no caller-controlled
filter, script, model path or partial overwrite.

Partition conditioning at cue boundaries. Eight-second contexts hold their last
actual scene frame rather than seeing the next scene; overlap/crossfade occurs
only within one direction interval. Short edge fades prevent clicks at direction
changes, while absolute frame/sample endpoints retain the complete original
film duration. One owned model load and ordinary effects Run produce the stem;
the existing separate preview Run remains unchanged. The native child verifies
the full source and the frozen cue list before publication.

Local prompt preparation includes each scene description as a separate bounded
field. The frozen source identity binds cue timings independently of editable
text, so neither a model nor a reviewed prompt can move a cue. Retry/original
recovery must restore scene wording as well as the overall description. Normal
contracts and actual multi-cue inference precede rollout; the prior basic effects
adapter stays deployed until those gates pass.

Scene direction qualification passed on the actual adapter: a fifteen-second
film used two explicit five-second scene directions and the overall description
for its remaining five seconds. All three model contexts stayed within their
own frame intervals, produced the requested distinct prompt records and exactly
661500 output samples, followed by the verified MP4 preview. Generation took
33.01s after loading/verification; measured peaks were 5073 MiB CUDA allocation
and 15.25 GiB scoped RAM, within the existing 8/18-GiB profile. This proves actual
conditioned execution and exact timeline coverage, not human auditory quality.
Final normal qualification has 136 passing cases across twelve complete
effects/native/translation/progress families and 55 UI cases across eight
complete families. Review also caught the legacy four-field translation bound:
scene preparation now explicitly permits eighteen exact fields, while other
generators keep four, and all sixteen cues can be reviewed/prepared together. Compiled
private desktop/mobile checks retain cue wording/times after generation,
refresh and next-version restoration, pass it through the typed native request,
compose a real preview and deny another account. Those browser checks substitute
GPU inference. Evidence: `data/acceptance/scene-sound-cues-20261030/`.

## Assistant and media-agent delivery (remaining NR-07)

Use the existing `EffectsRequest` and `create_effects_run` as the single source
of validation, admission, observations and source lineage. The unified assistant
must bind an explicitly selected or unambiguous owned film; text-only mentions
never authorize an arbitrary Library source. Expose the prompt, optional ordered
scene directions and resulting reusable effects WAV/linked preview in the same
conversation. Require ordinary media permissions and operational engine checks.

Media-agent definitions must display that same frozen film and sound settings
for review before activation. Their existing preparation, child Run dependencies,
approval, cancellation and recovery apply; do not add an implicit HTTP, shell,
external model or cross-account capability. Scheduled executions keep ordinary
Task/Run/Event/Artifact history. Test source ambiguity, Bob/admin inspection,
changed/unavailable sources, unavailable engine, approval, Stop and lost
acknowledgement before marking these entry points available. Shared native SFX
qualification is retained; human perceptual sound synchronization remains a
separate acceptance item. The timeline editor itself is deployed in PR #527.

The media-agent entry point is implemented in PR #528:
pure shared EffectsRequest schema, reviewed optional-until-activation film
selection, fixed/goal preparation with immutable scene timing, ordinary effects
and verified-preview children, existing approvals/Stop/receipts and private
results. Synthetic inference plus the real CPU compositor passed the compiled
desktop/mobile review/save/enable/run/refresh flow; this does not repeat or claim
new GPU inference/perceptual synchronization. Conversation source binding is the
next distinct delivery and remains in scope.

The remaining conversation delivery must cover both a reviewed existing film and
a newly requested film followed by its described effects on the same Task. Bind
explicit, unambiguous source authority; retain separate stems and cancellation
across stages. When a source contains speech/music, make replacement versus
layering visible and use the saved timeline mix to retain existing sound rather
than silently dropping it. These conversation flows are not claimed by the
media-agent delivery above.

### Conversation implementation checkpoints

1. Extend the typed assistant envelope with an optional effects scope, preserving
   legacy receipts when it is absent. Direct effects need no conversational text
   model. Reject mixed coding/data/runtime/music inputs and explicit simultaneous
   web research; ordinary default web is disabled for the admitted media action.
2. Bind only a manually selected owned film or one unambiguous completed film
   visibly produced in this conversation. Do not search arbitrary Library rows,
   guess between segments/finals or skip a latest unfinished/failed video task
   to reuse an older film. Snapshot its source identity before dispatch. Model
   routing alone cannot grant film access or initiate an unrequested operation.
3. Publish through EffectsRequest/create_effects_run, recording source binding,
   description/cues, child IDs and ordinary result artifacts in the conversation.
   Preserve approval, account, deadline, cancellation and recovery contracts.
4. Add the new-film flow through the existing video Task/Run dependency graph:
   complete/verify the film first, then admit its sound generation and final
   preview/mix. Never present a silent intermediate as the requested final film.
   Show progress and standalone stems, and retain prior/source artifacts.
5. Layer onto source speech/music through the existing saved timeline renderer
   with inspectable tracks/gains and a reopenable edit; expose replacement as a
   deliberate choice. Keep ordinary fixed-voice/music flows and receipts intact.
6. Qualify direct selection, referential follow-up, ambiguity/unavailable source,
   changed source, unsupported/unavailable engine, cross-account denial, Stop,
   lost acknowledgement and new-film→sound completion through real private
   API/worker/native boundaries and compiled desktop/mobile UI. Normal inference
   remains fake; perceptual/real-model acceptance is reported separately.


### Conversation delivery

The current candidate implements `audio.effects` in the unified conversation.
Choose **Attach files & choose tools → Add film sound**, select your private
Library film and describe its sounds. Auto also accepts explicit follow-ups such
as “Add sound to this film: rain on the leaves”. It binds the one completed film
shown in this conversation, including a verified linked media-agent result;
latest unfinished/ambiguous results never fall back to an older Library film.
The source identity is frozen before queueing and rechecked before native work.
Questions, quoted instructions, requests for an agent/prompt and unrelated scopes
do not grant generation or source access.

The default preview preserves original sound and layers the new WAV through a
saved timeline. **Original sound → Replace audio in the new preview** is an
explicit alternative. Independent levels, scene cues and advanced sampling remain
typed. **Edit sound mix** reopens the exact private timeline, its first saved
revision, render and creation-history turn; earlier/source files remain intact.
The conversation shows the film, a separately playable/downloadable effects WAV
and that editor link, with execution details collapsed rather than speech-clone
or destructive Library controls.

For new films, choose **Generate video → Add sound to this film** and enter the
sound description. Select a length to add precise scene directions. An explicit
Auto command can instead say “Generate a 15 second forest film with sound: rain
on the leaves”. The visual prompt and sound description are separate. This is
video-conditioned effects/ambience; narration and music remain distinct tools.
The existing Wan/segmented-composition graph publishes a container
`film_sound_prepare` Run dependent on the verified final film. It checks the
original reviewed scope, source bytes and frozen runtime observations, then
atomically publishes the normal effects Run. Sound and timeline capabilities
are inspected before child-publication transactions.

The final-film projection remains active until the sound-bearing render succeeds;
a silent segment/composition is never labelled as that requested final movie.
Task-wide Stop covers every stage. Explicit Resume on a full-film job whose
video already succeeded repeats sound preparation/generation only, retaining the
completed video. Resuming failed video stages rebinds sound to the new final
composition; old graph revisions and receipts remain inspectable. Uncertain owned
processes require inspection and are never blindly replayed. Ordinary effects
native cancellation/recovery and zero-swap resource limits are unchanged.

Qualification evidence is private under
`data/acceptance/conversation-effects-20261030/`. Normal inference is synthetic.
The compiled desktop/mobile conversation passes through a real private account
API, separate worker and native journal, with an actual scoped 4-GiB CPU timeline
render of 192 frames and 384,000 audio samples. Source/result privacy, reload and
editor reopening pass. This is not a new GPU-inference or perceptual-quality
claim. Review/merge/deployment are recorded separately. NR-06/07 audible and
scene-correspondence acceptance, naming and guided installation/catalog remain
part of the complete release objective.
