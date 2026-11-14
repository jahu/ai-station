# Longer video: temporal quality qualification

## Problem and evidence — 2026-11-13

The current Wan 2.2 TI2V 5B adapter generates at most 81 frames per invocation
(3.375 seconds at 24 fps). Longer continuous films recursively condition on the
last decoded RGB frame of the preceding window. APG limits exposure drift, but
does not retain the original subject reference or temporal velocity. A distorted
boundary frame can therefore become the next window's authoritative source.
The existing ten-second lake qualification covers exposure/detail, not moving
human identity, anatomy, arbitrary durations or instruction fidelity.

The official [Comfy 5B template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan2_2_5B_ti2v.json)
uses 121 frames at 1280×704, 20 steps, CFG 5. This is a concrete larger native
window to investigate, not evidence that a 12-GiB card or our bounded RAM profile
can execute it well. Fewer recursive boundaries may reduce accumulated error;
it cannot alone establish stable long-form generation.

## Work sequence and acceptance

1. Compare native 81/121-frame generation using the same neutral adult reference,
   prompt, seed, geometry, sampler and precision. Use private owned Tasks/Runs,
   kernel memory/zero-swap limits, absolute deadlines and measured VRAM/RAM.
   Preserve existing user work and external services. Record complete decoding,
   timing, all-frame samples and visual assessment, including facial detail,
   hands, motion and instruction completion. Never qualify only the first frame.
2. If qualified, freeze the advertised native window in each new timeline, with
   exact output duration and bounded overlap. Retain old frozen plans and retries
   unchanged. No public sampling graph, arbitrary executable or silent change
   to memory limits. Keep larger-window admission closed until actual proof.
3. Compare complete 10/20-second continuous outputs against the existing chained
   baseline, including every join and ending. Include a person moving/turning,
   a nonhuman subject and more than one seed. Record failure cases honestly.
   Inspect action progression too: replaying the same ordered instruction in
   every independent window can restart a completed action. If observed, add
   generic time-indexed motion phases through the existing frozen media plan,
   preserving shared identity/scene instructions and completed phase state.
   Do not add person-specific phrases or silently turn continuous action into
   independent shots.
4. Investigate a model trained for recurrent continuation with persistent anchor
   memory if base 5B still drifts. [Stable Video Infinity](https://github.com/vita-epfl/Stable-Video-Infinity/tree/svi_wan22)
   explicitly addresses accumulated errors and reference consistency; its Wan
   2.2 production branch targets 14B and needs a separate measured hardware fit,
   pinned adapter/dependencies/weights and owned preparation. Do not pretend its
   LoRAs work on the current 5B graph. [FramePack](https://github.com/lllyasviel/FramePack)
   is another low-VRAM recurrent model candidate, not an installed integration.
5. A coherent continuous shot is distinct from an intentional edited sequence.
   Preserve both user intents; do not disguise cuts, loops, slow motion, static
   images, face restoration or interpolation as a fix for failed generation.
6. Qualify ordinary worker/Runner execution, Stop, restart, reservations and
   composition before rollout. Review full diff and local checks, PR to develop,
   then preserving deployment only while idle. UI and orchestrator should choose
   the qualified recipe without making users tune internal continuation knobs.

This plan remains open until actual longer moving-subject films demonstrate
coherence and prompt fidelity on the target hardware. Tests, a calm scene or a
single successful native window do not establish that outcome.

## Candidate implementation and current gates

The candidate supports one fixed 121-frame window behind the native operator
qualification gate `AI_STATION_WAN_NATIVE_WINDOW_FRAMES`. Its default is still
81. The control plane uses only the Runner's observed capability; it cannot
choose an arbitrary window. Larger direct requests also require that capability,
and the Runner refuses them before file/process creation when its gate is closed.
New timelines freeze actual generated/retained frames. Existing publication IDs,
saved timelines, seeds, dispatches and avatar window sizes stay unchanged.
Standard RAM estimation accounts for the advertised larger decode window; the
reduced-RAM candidate retains its existing enforced 11-GiB/zero-swap bound.
There is no public UI switch or rollout while qualification is pending.

Local investigation evidence belongs to
`data/acceptance/long-video-temporal-quality-20261113/`. The first probe stopped
before inference because the environment parser rejected the text integer in a
Literal setting. That setup failure is retained under `attempt-1`; the corrected
parser accepts only the exact two documented spellings. The next owned probe
uses a fresh database and the unchanged native job, not an overridden sampler.

The publisher's [5B SVI development note](https://github.com/vita-epfl/Stable-Video-Infinity/blob/557afca50d5766514c67ae39000b03e0dd66d6e5/docs/DevLog.md)
is a preview. The inspected official model listing at revision
`f9bdd50c57e4c28f0d088b6bad8afa3fdc3bc1ac` contains no 5B weight. Its production
14B [Pro method](https://github.com/vita-epfl/Stable-Video-Infinity/blob/svi_wan22/docs/svi/svi_2.0_pro.md)
uses a persistent original-image latent plus the preceding motion latent, with
trained error correction. This is different from our old untrained raw-tail
copy. Reusing its conditioning trick on an incompatible 5B model is not an
evidence-based fix. Native-window qualification is the first comparison, not
a reason to close the larger recurrent-model work.

## Recurrent candidate: finite SVI Pro recipe

Publisher/SDK inspection identifies a concrete next candidate if the native 5B
comparison fails the longer-film gate. Its ingredients are staged only for
private engineering qualification; no operational SVI integration is advertised:

- SVI Wan 2.2 Pro source revision
  `bab066229ea530a09587bed52c41ed6089bd509f`. It conditions on the original
  anchor latent in every window plus one preceding generated motion latent.
  These are lossless tensors, not repeatedly decoded/re-encoded MP4 frames.
- Matching high/low-noise 14B models are both required. QuantStack repository
  `Wan2.2-I2V-A14B-GGUF`, revision
  `6c6717459277b9cd1f72579d78a0fd62a79e57dc`, publishes two Q4_K_M files of
  9,651,728,896 bytes each. Their size alone does not prove a 12-GiB inference fit.
- The two official SVI 2.0 Pro LoRAs at publisher revision
  `f9bdd50c57e4c28f0d088b6bad8afa3fdc3bc1ac` are 1,226,928,552 bytes each.
  Do not mix their expert roles or use older SVI conditioning with these weights.
  Full file identities/hashes are retained in private qualification metadata.
- This family needs the compatible Wan 2.1 VAE/16-channel latent geometry,
  not the current TI2V 5B VAE/48-channel geometry. Reuse the verified text encoder
  only after checking the actual model contract. Inspect all pinned SDK imports
  before running them; no arbitrary/custom graph endpoint is introduced.
- The inspected fixed GGUF loader supports dynamic low-rank patches without
  permanently expanding every quantized weight. Actual CPU/GPU allocation,
  compatibility with the installed core and frame quality still require proof.
  Use an isolated owned environment, finite kernel RAM/zero-swap bounds and the
  existing process manager. Never mutate the working Comfy installation.
- Preserve the qualified temporal rate explicitly. The inspected SVI reference
  script exports 15 fps; do not route it through our hard-coded 24-fps path.
  Timeline construction, composition, metadata and duration estimates need the
  same closed model-specific FPS, with legacy 24/25-fps plans unchanged.
- Qualification must include moving people and nonhuman subjects, multiple
  seeds, complete 10/20-second outputs and portrait as well as landscape intent.
  Separate model weaknesses from adapter/conditioning/decoding faults. Register
  a selectable production recipe only after native Stop/recovery, scheduling,
  source lineage, whole-film quality and ordinary worker publication pass.

This is a hardware-aware candidate rather than a promise based on model size or
an upstream demo. No larger weights were downloaded during the first comparison.

## First actual native-window comparison

The normal worker/private Runner comparison is terminal. Both runs used the
same neutral fictional-adult reference, prompt, seed 317749, 1280×704 geometry,
20 steps, CFG 5 and existing FP8/11-GiB zero-swap profile. No private sampler/job
override was used. Original source files, models and production storage remained
unchanged; only the isolated qualification database was written.

- 81 frames: complete decode, 664.7 seconds wall time. Sampled face/clothing/scene
  remain coherent, but the intended turn toward the camera is not clearly
  followed and the subject turns away later.
- 121 frames: complete decode, 1083.1 seconds wall time. Sampled face, coat/scarf
  and coast persist through five seconds without pronounced anatomical collapse;
  subtle gaze/head change, smile and hair/scarf motion remain visible. Reported
  peak RAM was 9,587,486,720 bytes under the same 11-GiB scope.

All comparison-owned native/worker/Runner processes stopped. The first baseline
reached its kernel RAM bound, so it must not be described as proving spare RAM.
This is a single-window result, not longer-film acceptance. A separate ordinary
publication has now queued a complete ten-second, two-window continuous film
with the same reference/instructions and the frozen APG continuation recipe.
Its output, actual join and ending still require visual evaluation.

Evidence: `native-window-probe.private.json`, `initial-visual-review.private.json`
and `full-film-probe.private.json` under the investigation evidence directory.
The source candidate passes repository Ruff/format and 200 affected normal tests,
including actual CPU composition after Stop/resume with fake inference. These
checks do not replace the pending real whole-film quality gate.

## Recurrent candidate preparation and broader comparisons

All five pinned candidate data files (two Q4_K_M experts, two Pro LoRAs and the
compatible VAE; about 20.5 GiB) have downloaded and passed their complete publisher
SHA-256 checks. There is one staged copy of each, no activation, and no change to
existing models or Python environments. The fixed loader and one GGUF wheel live
in an isolated private qualification directory.

CPU-only checks under a 4-GiB/zero-swap scope establish these limited facts:

- The pinned loader imports with the installed Torch/core and recognizes the
  actual high expert as a 40-block WAN21 graph, with 36 input channels and
  16 latent channels. This does not prove GPU inference or memory fit.
- Both official PEFT adapters map all 800 tensor keys to their expected 400
  rank-128 targets. Geometry comes from the actual quantized parameter's logical
  shape; the loader's `state_dict()` deliberately contains packed meta tensors
  for VRAM estimation and cannot validate the logical matrix shape.
- Initial and continuation conditioning match the pinned upstream Pro embedder
  exactly (maximum absolute error zero in both CPU comparisons). The core
  normalizes raw VAE values, so padding must represent `process_out(0)`, rather
  than raw zeros. The mask is also converted through the core's inversion rule.

A private fixed GPU job is prepared but not dispatched. It uses persistent
original-anchor conditioning, the bounded preceding motion tensor, separately
bound high/low experts, explicit FP32 VAE decoding and 15-fps output. The initial
engineering recipe uses 20 Euler/simple steps, shift 5 and the reference 0.875
expert boundary; this is a measured-candidate choice, not a claim of matching
the reference script's default 50-step quality. No acceleration LoRA is mixed in.
Kernel memory bounds, actual complete frames, timing and visual quality still
need real qualification before any product integration.

The existing 5B candidate now also has a separate 20-second/480-frame ordinary
publication from the approved synthetic car showcase image, with camera tracking
and moving water. It runs on the other discovered idle GPU while the person's
ten-second film continues. Each has its own private database/socket and enforced
11-GiB/zero-swap native scopes, retains the existing process/deadline ownership,
and yields to actual operator work. This broadens the quality check beyond a
person or a calm low-detail lake; neither pending film is accepted yet.

## Ten-second person result and remaining admission gates

The person film is now technically complete: 240 decoded frames/ten seconds,
two ordinary native windows plus composition, 2190.9 seconds wall time. Samples
throughout the output, including frames 119–122 at the join and frame 239 at the
ending, retain the face, hair colour, coat/scarf and coastal setting without a
pronounced exposure jump or severe anatomical collapse. Scarf/hair movement
becomes stronger after the join than the gentle-motion instruction. This case
passes sampled basic subject continuity, not arbitrary motion fidelity, smooth
temporal velocity proved from stills, portrait/full-body or longer-person quality.
Its three authoritative native records exited successfully and the complete
MP4 passed decoding/hash checks; the enclosing tool shell later reported 143,
so do not describe that shell status as a clean test-run exit. The separate
20-second object film is still running and remains an open quality gate.

Before rollout, scope larger-window admission to the actually qualified memory,
precision and geometry, or establish separate real evidence for the other
profiles. Current proof uses landscape and `bounded_11g`/FP8; the experimental
global window flag alone must not be interpreted as FP16 or portrait acceptance.
The eventual default must be selected through the ordinary frozen model/profile
path, with understandable UI choices and old plans preserved.

Full parallel verification exposed pre-existing parameter IDs containing random
UUIDs and timestamped workbook bytes. Only the display IDs in those two modules
were made stable; input data, assertions and test selection are unchanged. Their
91 tests pass with four workers. Complete parallel verification is running;
earlier collection failures and the interrupted serial fallback remain recorded,
not counted as passing checks.

## Scoped admission and recurrent timing preparation

The larger-window follow-up now binds admission to an available bounded FP8
profile, its advertised fixed geometry, at least twenty sampling steps and a
detected GPU with at least 12 GiB of dedicated VRAM. Only the tested landscape
geometry is advertised. An explicitly selected standard/FP16 profile and portrait
requests retain 81-frame windows. The legacy top-level capability also remains
81; new publication resolves the selected profile's closed `native_windows`
metadata. Auto may recommend the qualified bounded profile, while explicit
standard selection and previously frozen plans retain their identities.
Repository lint/format and 232 affected tests pass for this follow-up. Complete
regression is running in its isolated source checkout; the earlier interrupted
attempt remains unqualified.

The SVI candidate's 15-fps rate is now accepted by the internal timeline and CPU
composition contracts alongside the existing 24/25-fps rates. Existing video and
avatar publication defaults are unchanged; this does not register a selectable
SVI model. Actual CPU composition tests cover a 150-frame/ten-second output,
one-time trimming of the continuation context, final timestamps and complete
canonical audio at all three rates. Source timestamps must match the frozen
composition rate: a mismatched input fails instead of silently changing playback
speed. Unsupported rates remain rejected. Repository lint/format and 92 related
tests pass; this is timing/lifecycle preparation rather than GPU quality evidence.

A separate private SVI qualification observer waits for the existing twenty-second
film's actual cleanup, no compute processes and sufficient available host RAM
before it may enqueue one ordinary Task/Run through its private typed Runner.
Its fixed experimental adapter is registered only in that test worker process,
never in the application registry. Real inference, original-anchor consistency,
GPU/RAM fit, continuation, Stop/recovery and whole-film quality remain open gates.

Broader composition-consumer checks exposed a pre-existing scope leak from the
300-second workspace-footage extension: `AgentVideoRequest` inherited that ceiling,
although its reviewed editor, validation message and proposal instructions still
advertise at most sixty seconds. Restore the explicit agent ceiling; do not reduce
the workspace/Studio source-footage limit. Tests cover the accepted sixty-second
agent round-trip, rejected 61/300-second agent requests and unchanged 300-second
workspace schema. All 305 selected agent/avatar/Studio/composition tests now pass,
with repository lint/format. The initial failed test is retained in
`fixed-fps-consumer-check.private.log`; it is repaired, not waived. The ongoing full
run uses the earlier isolated source, so that known failing case there must be
reconciled with the repaired-source checks rather than described as a green run.

Pinned upstream [Pro inference](https://github.com/vita-epfl/Stable-Video-Infinity/blob/bab066229ea530a09587bed52c41ed6089bd509f/inference_svi_2.0_pro.py)
uses one motion latent and defaults its command-line continuation overlap to four
frames (the class constructor alone has a different overlap default). Preserve
that distinction in a future recipe. Internal timelines now also accept the
closed four-frame context value; old one/seventeen-frame strategies are unchanged.
The real CPU ten-second test trims those four frames exactly once and checks the
actual first retained pixel value at the join. This prevents a future adapter from
silently inheriting the 5B RGB-anchor overlap merely because both models use Wan.
Fixed-window recipes can also freeze a full native window for a short tail and
trim only during composition. An eventual 81-frame-qualified SVI adapter must
not silently sample 17/33 frames merely because the final requested duration is
shorter. The internal timeline supports this explicit strict-boolean policy;
legacy variable-size sampling remains the default. Duration/overlap tests include
one-, five-, ten-, twelve- and twenty-second plans with full 81-frame sampling.

## Complete twenty-second nonhuman result

The car/camera-motion case completed all four real native windows and ordinary
composition: 480 decoded frames at 24 fps, exactly twenty seconds, 4848.1 seconds
wall time. Every owned stage succeeded and all probe-owned processes stopped.
The final file hash and complete decode passed; no production data was changed.

Samples include each join and the final frame. The burgundy coupe's basic design
and harbor scene remain recognizable without pronounced bleaching or a clear
sampled cut. However, motion grows stronger after the first segment and the
ending has more blur and a substantially changed perspective. This is limited
evidence of subject continuity, not a pass for uniformly slow camera motion or
the full long-video quality goal. Descriptive successive-frame RGB changes also
increase after the initial window; those measurements are not a semantic quality
verdict. See `twenty-second-visual-review.private.json` and the complete output
in `nonhuman-film-probe.private.json` under the investigation evidence directory.

The first SVI GPU observer is alive and waiting for at least 25,600 MiB of actual
available RAM and no compute processes; the remaining regression workers still
occupy memory. It has not dispatched a native job. Do not restart that observer
or duplicate the completed car publication merely because admission takes time.

## Regression reconciliation and first actual recurrent dispatch

The complete isolated scope-source run reached its terminal result: 9,910 passed,
25 skipped and eight failed in 2431.1 seconds. This is not a successful regression
run. One failure is the agent-duration scope leak repaired above. The remaining
seven assertions predate the verified-edit coordinator or the later strict
terminal-planning contract; the corresponding application controller/decision
sources are unchanged by this investigation. Reconcile the tests to require the
coordinator before photo dispatch, technical failure for invalid exhausted
terminal decisions, and an actual `ask_user` action for genuine stale-source
clarification. Both explicit clarification and invalid-terminal failure must
preserve the old completed Studio result and forbid another production attempt.
Do not change the application to restore false-success behavior for those tests.

The conservative 24-GiB admission observer was stopped before any dispatch, with
its state/source preserved. A separate first memory-fit qualification now uses a
fixed 18-GiB/zero-swap kernel scope and sequential experts, with at least 19 GiB
available host RAM before admission. The first private wrapper attempt correctly
refused its mistaken artifact-only guard on a `runs/` directory before launching
anything; the canonical work-path guard was corrected and the failed attempt
retained. The subsequent real native Run is sampling its high-noise expert.
Initial observations show approximately 10 GiB VRAM and 15 GiB scoped RAM, with
zero OOM events. The low-noise expert, decode, complete output and actual visual
quality remain unproven. A read-only sampler retains per-stage kernel memory,
anonymous/file-cache usage, OOM counters and selected-device observations.

## Integrated verification and completed first recurrent window

The integrated source at `39ef618f` passes repository Ruff/format and the complete
Python suite: **9,957 passed, 25 opt-in cases skipped**, 2388.1 seconds. The prior
eight failures are repaired/reconciled, not waived. Real media/model work remains
separate from that normal fake-executor suite. The CPU-only cross-Task rehearsal
also passed ordinary composition of a retained prior clip and a new fixture:
150 decoded frames at 15 fps, ten seconds, four context frames trimmed once,
source artifact lineage preserved. Its inference was explicitly fake.

The first real SVI Pro Q4 window has completed through its private typed Runner
and ordinary worker: 81 decoded frames at 15 fps, 832×480, twenty steps/CFG5,
3169.8 seconds wall time. Both experts and FP32 VAE decoding succeeded on one
12-GiB GPU. Torch peak reserved memory was 10,175,381,504 bytes for the high
expert and 9,990,832,128 for the low expert. The kernel RAM peak reached the
18-GiB bound, with zero scope swap and no observed OOM; file-cache reclaim
occurred, so this is not evidence of spare RAM.

Eleven views across that first window retain the same face, hair, coat/scarf and
coast, with subtle gaze/smile and breeze motion. This permits a continuation
experiment, not acceptance of long-film quality. Its actual Run is
`a7b164cf-2377-4300-ab2c-6da19e1d717b`; the complete receipt, per-stage memory
samples and visual review remain under `svi-candidate/` in the evidence directory.

A separate actual native Stop probe canceled its owned process during input
verification (exit -15), adopted no output and released its resource locks.
That proves pre-sampling process cancellation, not GPU-phase Stop. A new
ten-second Task now reuses the completed first clip and its owned motion state,
preserves the original image, and samples the second window with a derived seed.
It will deliberately replace only its private worker during sampling, then require
inspection recovery with unchanged native PID/group/start time/deadline before
normal CPU composition. Recovery, the actual join/ending, longer-person and
portrait/full-body qualification, GPU-phase Stop and public model installation
remain open. SVI is not registered as an operational product executor.

The completed neutral 5B ten/twenty-second films and first SVI window were imported
into the owner's private Library as explicitly labeled QA artifacts. Import notes
retain their isolated provenance and unresolved quality caveats; no live Runs or
success history were invented. Only temporary import staging copies were removed.

## Encoding fidelity follow-up

Wan clips and ordinary composition previously left libx264 quality implicit,
unlike the existing CRF-18 Sonic and Studio paths. Every composition adds another
lossy generation; RGB-based continuation can also inherit that loss. This is a
secondary detail-loss source, not an explanation for all motion/identity drift.

A CPU-only comparison re-encoded the same decoded 81-frame SVI sample with
default options, CRF18 and CRF16. Compared with the decoded input, default encoding
measured 41.69 dB PSNR / 4.403 RGB MSE; CRF18 measured 43.11 dB / 3.176 MSE,
about 28% lower added pixel error. File size increased from 424,714 to 616,643
bytes, with similar measured two-second encoding times. CRF16 increased size
further for a smaller incremental improvement. The source was already compressed:
these numbers measure added encoding loss, not uncompressed diffusion quality.
Evidence: `encoding-measurement.private.json` under the investigation directory.

Use the fixed CRF18/medium H264 policy for Wan output and ordinary composition,
and retain that policy in artifact metadata. No client codec/filter options,
model/sampler changes, new permissions or output retiming are introduced. Existing
stored files remain intact. The actual CPU detail test uses a moving procedural
fixture and compares decoded output against the implicit default, alongside the
existing full-audio/timeline/ownership cases. Lint/format and 130 relevant tests
pass; the native GPU writer itself has not been rerun with the new encoder policy.
The ongoing private SVI continuation stays on its frozen earlier source.

## Actual recurrent continuation and product integration

The first complete recurrent ten-second film is now terminal: 150 fully decoded
frames at 15 fps, with the original image retained in both native windows and
one owned raw motion latent passed between them. The final film reuses the
already generated first 81-frame clip and retains 69 frames from the second
after its four-frame context. It does not stretch or loop a shorter clip.
The second native Run is `5f8b54f5-c8d7-44fe-801b-adac26e30c08`; composition is
`35da99b4-b058-4766-b1aa-8126f1c64417`. Its complete output SHA-256 is
`df03344ca5b77dfd1250400228c98a34545988d141d03855451a0184e4411f10`.

Seventeen sampled views include the actual frame-80/81 join and final frame.
Face, hair, coat/scarf and coast remain recognizable without obvious sampled
scene jumps or severe anatomical collapse. Later frames develop gaze/head
movement and a blink. This is calm, half-body landscape footage; it does not
establish dynamic full-body, portrait-orientation, multiple-seed or long-film
acceptance. The original and result are private owner Library QA artifacts.

The worker was deliberately replaced during sampling. After lease expiry,
ordinary inspection resumed the same native PID/group/start ticks and absolute
deadline, without restarting inference. All test-owned processes stopped after
composition. Stop during input verification also passed; GPU-phase Stop still
requires its own actual test.

A twenty-second Task now reuses both complete native clips and generates only
the next two. Its retained frame counts are 81, 77, 77 and 65, totaling exactly
300 frames at 15 fps. Reusing the second full native clip restores its unused
tail before the next motion state; chaining from the trimmed ten-second export
would skip that state and is not allowed. The worker resolves each prior motion
artifact only after success, checks same-owner provenance, original image,
profile identity, trash/purge state and unchanged frozen source observation.
CPU rehearsal accepted valid/idempotent binding and rejected nine changes to
ownership, source identity, checkpoint lineage or availability. Actual longer
generation and its join/ending review remain pending.

Product integration keeps these boundaries:

1. `wan_svi_context` and `wan_svi_adapter` provide the closed Wan21 conditioning,
   bounded SafeTensors header and complete 400-target/rank-128 PEFT bridge. They
   import no AI dependencies at application startup and register no executor.
   Production motion metadata uses `station.svi_profile`; private candidate and
   old 48-channel 5B checkpoints cannot be silently adopted. Native dispatch
   must bind the complete recipe/implementation, original anchor and components
   before supplying this identity. The checkpoint header is not a substitute
   for canonical owned paths, whole-file hashes or account provenance.
2. Extend existing reviewed model bundles and runtime preparation with the two
   pinned Q4 experts, two matching Pro adapters, compatible 16-channel VAE, text
   encoder and pinned GGUF SDK/wheel. Reuse verified store objects; do not expose
   raw paths, editable model graphs or mutate an existing runtime. Structural
   inspection alone never grants inference readiness.
3. Add a distinct typed native SVI dispatch and executor identity over the
   existing process manager and `HostMediaExecutor`. Keep the measured 18-GiB
   zero-swap scope and 12-GiB GPU admission. Original anchor and preceding motion
   remain separate typed owned inputs; every window preserves its source/hash,
   derived seed and deadline. Test GPU Stop, restart and lost acknowledgements
   before registering this as an operational executor.
4. Bind shared model definitions to this complete recipe. Model capabilities,
   rather than the 5B hard-coded defaults, select dimensions, 15 fps, full
   81-frame sampling and four-frame context. Workspaces, assistant tools and
   reviewed agents must use the same frozen recipe and exact composition.
   Timing estimates need a separate recipe identity and must respect the
   user's execution budget; a measured slow model is not silently promised to
   finish a long job within the existing four-hour agent maximum.
5. Qualify moving/full-body and nonhuman scenes, multiple seeds and portrait
   intent, then expose a clear installed model choice and preserving deployment.
   Lower-resolution acceleration is a separate measured recipe, not an
   unsupported FPS reinterpretation or untested sampler reduction. Sound/effects
   must retain real time when handling 15-fps output.

The checked repository conditioning matches the pinned Pro embedder through the
actual installed core on CPU for both initial and continuation cases: maximum
absolute error zero, with seven invalid context cases rejected, including
non-F32 anchors. Normal tests use
bounded synthetic tensor headers/matrix geometry and load no model. This proves
the bridge mathematics/storage contract; it is not public runtime readiness.
The repository PEFT bridge also mapped both actual pinned adapters on CPU to
all 400 targets/800 tensors at rank 128 and strength 1.0. That check used the
high expert's common target geometry for both adapters; it did not run inference
or independently qualify low-expert generation. The 33 focused normal tests
cover the new contracts and existing 5B motion handling without AI dependencies.
Private evidence remains under `svi-candidate/` in the investigation directory.

The reviewed `08bf9501` baseline is now deployed to the target station. It
advertises the qualified 121-frame option only for the bounded 1280×704 recipe
and retains CRF18/medium encoding for new ordinary video/composition outputs.
The preserving rollout checked exact existing account/content table bytes,
database integrity, unchanged LAN binds and the same enrolled Tailscale node and
HTTPS origin. The owned Tailscale daemon's process/Run identity legitimately
changes during native service restart; it is distinct from the persistent node
identity. The private twenty-second SVI probe continues independently. This
deployment does not enable SVI or claim that the full quality goal is complete.

## Owned native SVI integration in progress

The candidate now has a separate fixed
`wan22-svi-pro-q4-linux-x86-64-python312-v1` recipe and offline assembler. Its
107 inputs retain the exact existing 5B engine's Python/coherent dependencies,
add the pinned GGUF SDK/wheel, and select six SVI model components. They exclude
the unused TI2V 5B diffusion/VAE weights. Preparation reuses verified store
objects, creates its own Python/source namespace, executes an offline CPU-only
tokenizer/loader probe and publishes readiness only afterward. Opaque shared
engine identities hide private setup Run IDs. This assembler is implemented;
guided setup Tasks/catalog admission and an actual fresh environment preparation
are not yet qualified or exposed.

Typed native `/v1/video/svi/capabilities`, model-capabilities and `/v1/runs/svi`
operations now exist behind the closed qualification flag. The default reports
unavailable and refuses execution. A dispatch accepts only its opaque engine,
original owned PNG/JPEG, optional matching owned motion tensor, prompt, derived
seed, allocated GPU, explicit permissions and absolute deadline. It cannot choose
a graph, executable, arbitrary resolution, steps or sampler. The native child
rechecks the canonical request, actual 18-GiB zero-swap scope, exact Python/SDKs,
complete six model hashes, source hashes and implementation/anchor motion
identity before sampling. It preserves sequential experts, FP32 VAE, 15 fps,
the trained anchor/motion conditioning and fixed CRF18 export. Nonfinite samples
or decoded pixels cannot publish a result. The control-plane executor and model
selection still need integration; these native endpoints do not make a new
operational product capability.

Repository lint/format and 280 affected normal tests pass, covering owned
assembly, tamper rejection, typed dispatch, the old video profile, platform/API
boundaries and process/deadline behavior. A real process-group test uses an
explicitly fake engine, reattaches its same native identity after manager
replacement, then escalates Stop against only that owned group. It is not a GPU
inference or GPU Stop test. A child-import test denies API-server, eager Torch
and network imports. New-job fresh-runtime inference remains pending.

The earlier unregistered-core whole-suite attempt was deliberately interrupted
when this wider native work changed the source beyond its original collection:
1,818 passed in 2458.1 seconds before KeyboardInterrupt, with no observed test
failures. This is not a full-suite pass or validation of the expanded head.
Retain the earlier complete 9,957-case baseline separately; use a frozen source
for final broad verification rather than repeatedly testing a changing checkout.

## Completed twenty-second recurrent film

The actual four-window person film completed: 300 decoded frames at 15 fps,
exactly twenty seconds. The first two full native windows were reused; only
windows three/four and composition were new work (6310.3 seconds). All owned
processes stopped and resource locks were released. Final CPU composition used
the fixed CRF18 policy. The final artifact is
`5c17ec5d-5102-4294-8e34-31b9356aef88` in the isolated qualification database.

Twenty-four views include joins at frames 81, 158 and 235 plus final frame 299.
The same recognizable face, hair, coat/scarf and coastal scene persist without
obvious sampled scene jumps, severe exposure bleaching or anatomical collapse.
Gaze/head movement, blinks and breeze remain visible. Detail is still 480p, not
HD. This permits further qualification; calm half-body footage does not prove
dynamic/full-body, portrait or other-subject behavior. The complete film was
imported into the owner's private Library with diagnostic provenance and no
invented live execution history. See `svi-candidate/twenty-second-review.private.json`.

A separate 512×288/50-step car candidate now reuses the same pinned weights and
the earlier approved synthetic car source/prompt/seed. It waits for confirmed
completion and process exit of the twenty-second probe, no actual compute work,
19 GiB available RAM and operator priority before dispatch. Its first real high
expert steps measured about 40 seconds each, compared with about 146 seconds
for the earlier larger geometry. This is a partial observation, not a complete
runtime or quality result. Fifty steps follow the reference recipe's count;
the candidate remains private and does not change public sampling defaults.

## Shared worker integration in progress

The control plane now has an unregistered SVI adapter and queued-segment creator
over the existing `HostMediaExecutor`, Task, Run, Events and Artifact services.
They freeze the exact native engine/model observation, eligible devices and
owned original image, reserve 18 GiB RAM and cap each native child to one hour.
Continuation binds only a succeeded same-owner SVI producer with unchanged
original image/engine and an available video→motion provenance chain. Binding
is idempotent, records one structured event and refuses a modified frozen
snapshot. Internal motion artifacts declare four context frames and their
profile identity; the old 5B default remains seventeen frames.

Whole worker tests with fake native media cover two dependent windows, state
collection, resource release, stale-worker inspection recovery without another
native start, and cancellation on resume without artifact publication. SVI
progress reports truthful high/low-expert phases; separate 9/11-step bars are
not interpreted as complete twenty-step job progress. Timing histories retain
the distinct executor/backend/geometry signature.

The expanded affected backend group passed 137 tests. A later model-snapshot
freezing change and additional regression passed the final 45 focused SVI
tests. These normal tests use temporary databases/fake executors, not real GPU
inference. Public creation/model routing, guided installation, model-aware
frozen timelines/composition, UI choices and fresh managed-runtime/GPU
qualification still gate registration and availability. Existing videos remain
on the deployed reviewed 5B path.


## Owned SVI setup lifecycle

The fixed native setup protocol now covers catalog, prepare, inspection, Stop
and explicit adoption through `OwnedEnvironmentPreparation`. It reuses the same
4-GiB bounded offline assembly process, immutable request/journal and opaque
engine publication. The only accepted recipe is the pinned 107-input SVI
manifest. Catalog reports actual GPU/RAM/driver/storage constraints and component
licenses, including the separate MIT Pro adapters and Apache-2.0 GGUF SDK.
Preparation and adoption share the native SVI qualification flag; both remain
closed by default, including adoption after an earlier process has completed.

The ordinary administrator runtime-setup API now recognizes this profile and
queues an `svi_setup` Run. Its executor reuses verified resumable downloads,
checks the six distinct component roles, and publishes model files plus the
private setup receipt through the existing services. Native setup processes and
media generation remain distinct operations. Account-worker admission, revoked
administrator cleanup, lease recovery and queued cancellation recognize the new
setup executor. No frontend operational model choice is enabled by this change.

Normal tests cover the fake complete API/download/native/adoption path, corrupt
inputs, Stop before and after dispatch, immutable resume, stale worker fencing,
private setup history, account revocation and resource release. The offline child
also rejects foreign requests/recipes, missing journals, naive or expired
deadlines, and observes durable Stop during assembly. These checks install no
real engine and are not fresh-runtime or GPU qualification.

The setup change passed 102 affected native tests, 34 setup-worker regression
cases across the SVI/5B paths, 71 shared setup/account/recovery and recurrent-run
regressions, then the final 19 SVI setup cases after adding incomplete-component
and closed-catalog regressions. Repository Ruff and format checks passed. These
are focused checks, not a new full-suite pass or real installation evidence.


## Recurrent CPU composition and lower-resolution observation

CPU composition now accepts the closed SVI engine identity alongside the existing
5B identity. The parent chooses the explicit SVI environment, checks its admission
flag and refuses unavailable/changed receipts instead of falling back to a
configured 5B Python. The offline child independently resolves the same frozen
profile and requires its exact prepared interpreter, CPU resource scope and
absolute deadline. The resolver imports no Runner API. Legacy 5B explicit-path
precedence and requests without a managed identity retain their behavior.

The final 146-case native/platform group passed, including actual tiny CPU encode/decode
of two synthetic 81-frame clips into 150 frames at 15 fps, with four-frame context
trimming and CRF18 output. The managed environment in this test is synthetic;
it is not a fresh SVI installation or real GPU result. Negative tests reject
foreign Python, unknown profiles, arbitrary paths and unqualified/missing engines.

The private 512×288/50-step nonhuman candidate completed its first 81-frame window
at 15 fps in 2236.5 seconds, including its actual worker/native execution boundary.
All frames decoded and all owned processes stopped. Eleven sampled views preserve
the recognizable harbor car, grille, round headlights, wheels/windows and scene,
with a visible lateral camera reveal. This is low-resolution detail and only a
5.4-second observation, not broad long-video quality qualification. The checked
film is in the owner's private Library. A ten-second continuation now reuses its
first window and original anchor; no repeated initial generation is required.
It uses the same method's separate 512×288 motion identity, not a relabeled public
832×480 checkpoint. This measurement does not yet change the product recipe.


## Shared recurrent model registration

Successful SVI setup now registers one shared Video definition for its complete
six-component bundle and opaque prepared engine. Each component retains its
owned registry ID, hash, relative store path, byte size and mtime; selection
rechecks all six and the primary high-noise model. The definition binds the
actual fixed geometry, 15-fps timing, four-frame context and 18-GiB workload.
Shared metadata contains no private setup operation ID. Registration is
idempotent for the same environment and refuses conflicting bindings.

SVI setup requires separate explicit CPU-offload/workload acceptance in addition
to license acceptance. Older runtime setup requests keep their existing contract.
The shared offline-setup executor has a default empty post-preparation hook;
SVI alone uses it to register the complete model before its private setup receipt
and success transition. Other media setup paths retain their receipt format.

Video model capabilities select the SVI typed engine endpoint without passing a
5B checkpoint slot. Incompatible engine/geometry/fps/context/resources are
rejected. An unregistered recurrent execution adapter cannot be advertised as
available, even when an isolated native test engine reports readiness. Short/
long public dispatch and UI admission remain separate outstanding work.

The existing model-install Run also has a metadata-only SVI bundle recheck; it
does not parse the GGUF as a conversational model, download weights or load a
GPU. It preserves the frozen bundle, claim fencing, Stop and administrator
checks, and returns an honest metadata-only receipt (no new full weight hash or
inference claim). Native inference retains its full six-object hash validation.
Focused tests cover selection tampering, private-ID exclusion, immutable
snapshots, typed capabilities, consent, recheck cancellation and stale claims.

The integrated registry/setup group passed 195 tests in 260.2 seconds, including
existing 5B model installation/definitions and speech/music/avatar/effects/Fish
setup regressions. Repository Ruff and format checks passed for 1,393 files.
This remains focused normal-test evidence, separate from actual owned assembly,
new native inference and final whole-source validation.
