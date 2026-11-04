# Guided local video setup

NR-14 continues after the delivered conversation, speech, image, CPU-memory and
music profiles. The first fixed Linux NVIDIA profile has passed isolated real
qualification and is enabled in the reviewed implementation. Merge and production
deployment remain separate gates.
Preserve the existing configured Wan adapter, its long-film coordinator, image
animation, continuation/APG recipes, saved creative sessions and exact Resume.
Do not change the external ComfyUI checkout, its Python environment or models.

## Starting evidence

The working configuration uses a clean ComfyUI checkout at
`387f98aa2822f684b8597959a52a467d88cc4806`, a separate Python environment and three
Wan 2.2 5B safetensors companions: diffusion model, UMT5 text encoder and VAE.
The text encoder resolves into an existing host cache; discovery is read-only.
The three configured files total 18,144,966,705 bytes. Verify their complete
hashes/lengths against pinned publisher metadata before defining a recipe;
filenames and existing paths alone are insufficient provenance. The audit now
matches all three complete files to publisher revision
`ee6f4a40737a995bf5818954cfce6d59443b0f04`. The visible metadata includes 108
entries because the environment can also see base packages; eleven names have
multiple versions. Import precedence and installed RECORD payload checks select
97 active versions, including Torch 2.11 / torchvision 0.26 / torchaudio 2.11.
Their complete dependency graph, including requested extras, passes 132 checks.
All selected wheels have exact public PyPI sources (2,929,344,463 bytes).
The pinned source archive's 912 Python files exactly match the clean configured
checkout. The candidate recipe freezes 102 objects totaling 21,120,942,860 bytes;
this is audited input provenance, not runtime readiness. The new environment
must be independent of visible base packages and pass its own offline pip check.

The active Torch 2.11 environment uses CUDA 13.0.2. The first fixed profile
will conservatively require Linux driver version 580.126.20
from [NVIDIA's archived release notes](https://docs.nvidia.com/cuda/archive/13.0.3/cuda-toolkit-release-notes/index.html).
This is a profile admission floor, not a claim that earlier R580 drivers never
support CUDA compatibility. Detect and report incompatible drivers; never install
or change them. A broader older-driver recipe needs separate qualification.

The [publisher model card](https://huggingface.co/Comfy-Org/Wan-2.2) declares
Apache-2.0. ComfyUI carries GPL-3.0, with its own
[upstream source/license](https://github.com/Comfy-Org/ComfyUI).
Python, Torch/CUDA and other dependencies retain separate licenses. A setup card
must disclose those components; do not label the whole runtime Apache or MIT.

## Delivery contract

1. Freeze a built-in recipe with the reviewed source archive, a standalone
   Python, a coherent exact binary-wheel set and all three model companions.
   Audit the configured environment's dependency metadata instead of blindly
   copying its package list. Any required compatibility adjustment is confined
   to the new managed environment and must pass dependency/import/inference
   checks. No user-selected URL, package, code, command or destination is accepted.
2. Reuse the shared immutable downloader, ordinary owner-scoped preparation
   Task/Run, setup worker, native offline preparation journal and four-GiB setup
   scope. Preserve deadlines, immutable identities, Stop-before-dispatch,
   lost-acknowledgement inspection, worker/claim/revocation fences and explicit
   adoption. Complete cached inputs can be reused without changing originals.
3. Assemble an independent offline runtime. Verify source/model bytes before
   imports and permit only exact closed-world managed links to immutable model
   objects. The configured external path behavior is preserved. Disable custom
   nodes, API nodes, upstream downloads and any ComfyUI web server; invoke the
   existing fixed headless video job. An incomplete environment never becomes Ready.
4. Add managed fallback selection only when *none* of the existing video Python,
   source or model settings is explicit. Partial configuration must show its
   repair requirement. Freeze the managed recipe/environment, compatible GPU,
   model observations and absolute deadline in ordinary video Runs and full-film
   plans. Revalidate them before dispatch/import, continuation and publication.
   Never silently reroute a saved plan or Resume to changed sources.
5. Reuse the qualified bounded Wan loader/resource contract. Report GPU and
   CPU-offload RAM requirements from measured evidence; gate unsupported hardware.
   Preserve the long-film UI/coordinator and complete exports rather than
   narrowing the guided route to a short clip. Sources, motion checkpoints,
   artifact lineage and saved progress remain inspectable and owner scoped.
6. Extend the existing Models setup design and Video's missing-runtime entry.
   Show hardware, free/required storage, actual component licenses and reviewed
   sources before consent. Restore measured download/native preparation progress,
   Stop/Resume and history; offer Open Video only after real runtime preparation.
   Existing explicit integrations retain priority and an optional managed-copy
   action. Keep the desktop and phone experience consistent with other setup cards.

## Qualification and release gates

Normal tests use small synthetic files, temporary databases and fake processes.
Cover pinned source/model validation, archive/path/link boundaries, offline
assembly, coherent dependencies, frozen/repeated preparation, interruption,
Stop/adoption races, stale claims/revocation and account-private histories.
Test the managed dispatch through the existing short video, image-animation and
full-film builders, including frozen sources/deadlines on continuation/Resume.

Opt-in qualification uses an isolated fresh account, real API and separate
worker, compiled desktop/phone and native setup. Stop/Resume actual preparation;
generate and decode a complete video, verify exact frames/duration and Library
playback/seeking, then verify a continuation/full-film result and animation.
Exercise native restart retaining the same owned process, Stop with no partial
publication, resource release and second-account denial. Do not substitute one
tiny native probe for the complete application or long-film contracts.

Keep new preparation unavailable until the fixed profile passes those gates.
Review the complete diff and local equivalent checks before a PR to `develop`.
An idle-only rollout backs up the database and proves preservation of configured
media, models, memory/index, credentials, histories and private remote access.

Private audit evidence: `data/acceptance/guided-video-setup-20261031/`. This work
does not complete avatar/effects/expressive-voice setup, broader hardware/source
catalog choice, consumer Linux/Windows/macOS install/update/uninstall, NR-06/07
quality acceptance, naming or the final operator QA workbook.

## Implemented contracts and measured qualification

The recipe now prepares all 102 verified inputs, an independent Python and 97
coherent binary wheels. A fresh-account compiled UI exercised actual native
installation Stop/Resume and restored its completed setup after a restart.
The prepared SDK/tokenizer imports pass offline without GPU inference; real
inference is qualified separately, rather than claimed by a readiness probe.

The first isolated native text-video result decoded all 17 frames at 1280×704
under the 11-GiB/zero-swap profile in 241.52 seconds. A subsequent ordinary
API/worker generation animated an uploaded image into 33 frames and retained
source lineage. A two-segment continuous film produced and decoded its complete
96-frame/four-second export, with compiled Library playback and phone layout.
These are those exact tests, not evidence that every duration/scene is inspected.

That full-film test found a composition configuration bug: the final CPU stage
still required an external Python despite successful managed GPU segments. The
fixed composition dispatch freezes the same opaque environment, admits four GiB
of CPU RAM and executes CPU-only in its own zero-swap scope. Explicit Resume
reused both completed GPU segments and retried only composition. The failed
attempt remains in history. The prepared PyAV environment also supplies the
existing timeline editor when no external codec runtime is configured.

Manual managed films retain a 72-hour absolute whole-film expiry; individual
native video/composition processes keep their one-hour ceiling (the CPU codec
child also retains its shorter 30-minute limit). An explicit reviewed agent
deadline is never extended. Short generation has a 24-hour queue/workflow expiry.
Those budgets are bounds, not estimates or promises of generation speed.

Second-account checks deny the owner's setup, generation, whole-film Task and
artifact file while exposing shared readiness through an opaque hash. The native
private mapping is written inside the adoption lock before the active pointer;
a failed mapping publication preserves the previous active environment. Partial
external configuration never falls through to a different managed installation.

Actual Runner restart recovered the same PID and start time during generation.
Ordinary API Stop ended that owned process without a partial artifact and released
its resource reservations. The compiled editor also saved, rendered and restored
the complete 96-frame film through the prepared CPU environment on desktop/phone.

Normal qualification includes the complete 1508-test native suite (two explicit
opt-in skips), the 1037-test frontend baseline plus the final 28 affected UI
cases, 240 backend cases before the composition correction and complete final
composition/consumer families afterward. The native suite exposed an unrelated
private-process registry race: validation could overlap the owned exit thread's
atomic replacement. Validation now shares that manager's lock, preserves strict
file checks and passes a deterministic contention regression and the full suite.
These are local equivalent checks; hosted Actions remain manual by owner policy.

Final compiled desktop/phone qualification passed without the private activation
override. It restored setup attempt two, the complete film with decoded seeking
and the saved editor export; the separate fake worker/API/SSE test also passed.
All 593 application/frontend files and 173 native wheel files match the reviewed
source. Final composition/consumer checks pass (87 and 115 cases respectively),
alongside native policy, lint/format, TypeScript, production build, all three
Compose variants and the Docker image. Operator catalog v26 retains unanswered
SETUP-121–125; internal checks do not fill in the owner's QA answers.

PR #542 was reviewed, squash-merged into `develop` and deployed while idle with
a database backup. All 38 existing table snapshots, credentials, configured
video/image/music/speech integrations, shared models, memory/index and private
node identity were preserved. The production compiled setup/workspace passed
desktop/phone checks; its temporary audited device was revoked. Exact isolated
QA services were removed while retaining verified inputs, generated media and
private evidence. This completes this fixed video profile, not the full release
or the remaining guided media/consumer-platform work.
