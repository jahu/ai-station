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
