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
