# Wan continuation: preserve exposure and detail

Candidate implemented; qualification in progress, 2026-10-26. This is a visual-quality release gate,
not a claim that a decodable MP4 is an acceptable long video.

## Reproduction and evidence

The actual natural-agent ten-second lake film used four normal-worker/native
Wan windows at 1280×704, 20 steps, CFG 5 and the bounded 11 GiB/zero-swap profile.
Generation, assembly, 240-frame decoding and compiled desktop/phone playback
passed. Exposure progressively increased and detail disappeared: the final
sample's nearly-white area was about 60%, versus below 1% initially. The older
four-step 60-second artifact also degraded. More steps alone did not fix it.
Retain both technical passes and the explicit visual failures.

Receipts: `data/acceptance/long-video-standard-20261025/` and
`data/acceptance/long-media-visual-audit-20261025/`.

The legacy native path copies the previous denoised tensor's last five temporal
slices into the next window's first five slices, locking their noise mask. The
installed Wan VAE starts encoding/decoding with a distinct one-frame boundary,
then uses causal temporal caches. A tail from the middle of a video is therefore
not equivalent to an independently encoded seventeen-frame prefix.

An opted-in, read-only VAE diagnostic on the actual first window confirms a
boundary mismatch before diffusion: decoding its raw tail gives mean absolute
pixel error 0.0192, versus 0.00191 when re-encoding the previous seventeen RGB
frames. In the first reconstructed frame, nearly-white area rises from 0.11% to
10.97% with the raw tail, versus 0.16% after pixel re-encoding. Original weights,
installed runtime and production database are untouched. Float64 per-frame PNG
statistics are authoritative; the original all-frame float32 mean calculation
is marked imprecise and must not support a quality claim.

Receipt: `data/acceptance/wan-continuation-quality-20261025/`, including source
hash checks, diagnostic images and `vae-image-statistics-float64.json`.

## Next experiment and implementation contract

1. The already-shipped pixel-prefix fallback was exercised with the same first
   clip, prompt, seed, steps and memory profile through an isolated normal worker
   and private Runner. It fixes the prefix and reduces the ending's nearly-white
   area from 29.35% to 14.29%, but generated frames still brighten substantially.
   **This alone fails the visual gate and is not an accepted product fix.**
   `pixel-probe-result.json` preserves technical success and explicit visual
   failure. The original database and source clip are unchanged.
2. Compare single-image conditioning against seventeen-frame conditioning, and
   default weight precision against the fixed reduced-memory FP8 profile. Keep
   the same scene/seed/steps; use separate owned processes, GPU allocations and
   kernel RAM/zero-swap bounds. The official Comfy 5B template confirms existing
   UniPC/simple/shift-8/20-step/CFG-5 sampling, so there is no evidence yet for
   changing those defaults. The downloaded primary template and its hash belong
   to the diagnostic evidence. Do not expose engineering precision/scope knobs.
   The single-image test is terminal: final nearly-white area is 0.148%, versus
   29.35% cached and 14.29% pixel-prefix. Detail is retained, but some exposure
   drift remains; this is not a long-film or motion-velocity qualification.
   The first default-precision diagnostic hit its fixed 12 GiB memory cap and
   stopped without a quality result. A separate 16 GiB/zero-swap diagnostic
   completed: its ending was 26.55% nearly white, retaining the same degradation
   with a correctly encoded seventeen-frame prefix. FP8 alone does not explain
   this failure. No service or production configuration was changed to enlarge
   that private test scope. Retain all receipts, including the failed scope.
3. The candidate freezes `last_frame_v1` in newly published video Tasks and every
   segment/compose Run when the Runner advertises one-frame continuation.
   The native typed request accepts only exact integer prefixes 1 or 17; the
   one-frame form requires an owned preceding clip and forbids raw checkpoints.
   It verifies the clip hash and dimensions, decodes at most 81 frames and
   conditions on its actual last RGB frame. A single overlap frame is omitted
   from composition, preserving the exact requested duration. Ten seconds now
   needs three windows rather than four, without lowering steps/resolution.
   Old Runners select an explicitly frozen legacy strategy; old plans and
   resumes retain the original absent strategy/seventeen-frame timeline.
   Unknown strategies fail closed. Default native serialization omits the new
   field, preserving legacy dispatch identity. Historical JSON is not migrated.
   Review also binds a present strategy into prompt-translation input identity;
   changing it after translation must prevent dispatch. Absent fields retain
   their exact pre-strategy receipt hashes. Two regressions reproduced the gap
   before correction; all22 translation-module tests pass after correction.
4. Preserve temporal continuity and record the actual conditioning overlap in
   the frozen timeline. Keep frame counts, seed, prompt, deadline,
   ownership, hash/path validation, cancellation, resources and composition.
   Do not substitute cuts, global colour filters or external inference.
5. Cover publication, frozen/legacy dispatch, missing or trashed prerequisites,
   unknown strategy and current/legacy resume with normal fake/CPU tests. Reuse
   existing native validation and pixel decoding; no new shell or graph API.
6. Qualify a real multi-window output, including seams and ending, before claiming
   corrected long-video quality. Review the full diff, run required local checks,
   then PR to develop and deploy only a satisfactory reviewed release.

A good result for one lake/profile is not proof of arbitrary durations, scenes,
identity fidelity or all installed models. Keep the final Polish operator QA
package's profile descriptions aligned with the actual verified outcome.
Single-frame anchoring also does not prove preservation of temporal velocity
across windows. The candidate still needs a complete multi-window visual gate
before review/merge/rollout; this document is not a deployment receipt.
