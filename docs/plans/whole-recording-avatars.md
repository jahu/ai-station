# Stable whole-recording avatars

2026-10-28, QA-020. Implementation in progress; the production default is still
Echo. A downloaded model or native experiment does not advertise an available
application executor.

## Evidence and decision

The retained Echo 384-px/8-step recording develops progressively different facial
details, especially eyes. The owner rejected that quality. Prior conditioning
ablations did not meet both appearance and continuity requirements; retain their
negative results and the original QA failure.

A separate, pinned Sonic evaluation generated the same complete neutral portrait
and 40.08-second recording. Native generation took **3131.22 seconds**, with a
Torch allocated peak of **5,472,745,984 bytes** on one RTX 3060 12 GB, while the
original two-GPU llama.cpp model remained ready. These are measurements of the
256×384, 25-step profile, not universal hardware requirements or speed claims.
CPU RIFE produced **1002 frames at 25 fps**; video and audio both measure 40.08
seconds. Real complete browser playback, downloaded bytes and narrow-screen
layout passed. Viewed samples at 0/10/20/30/40 seconds retain substantially more
consistent eyes, facial appearance and skin color than the adverse Echo result.
This is promising evidence for integration, not a repaired application workflow
or subjective lip-sync acceptance.

Source is pinned to `c1bd2d133ecc72f1a5abd990f1de101efcc3cfdb`. Required weights were
separately downloaded and verified. The original runtime, model files, drivers and
CUDA were not modified. Private evidence remains under
`data/acceptance/browser-qa-20261026/`; no portrait/video is published with this
document. Source and component licenses remain separate. See
[model comparison](avatar-model-quality-evaluation.md).

## Application contract

- Add an explicit, typed, frozen whole-recording profile. Omitted fields preserve
  old Echo request serialization, saved plans and reviewed agent identities.
  New requests select the profile before enqueue; resume never follows a changed
  recommendation. Bind the exact implementation/model observation.
- Generate one global latent sequence for the complete recording, then decode,
  interpolate and mux the complete canonical audio in one owned process tree.
  Do not concatenate independently generated short portraits. Keep ordinary
  Task → Run → Events → Artifacts, effective permissions, native budgets,
  cancellation, journal inspection, leases and explicit retry semantics.
- Existing `MediaTimeline` segments are bounded to 81 frames. Preserve that
  contract. A versioned whole-recording plan needs real single-stage progress,
  final Artifact publication and a dedicated resume branch; do not fabricate
  composition Runs or duplicate stage IDs to fit a segmented plan.
- Expose only a typed private Runner operation, configured local model/runtime
  roots and a fixed native entry. No caller-supplied commands, paths, graphs,
  Python or model code. Validate source hashes, symlink boundaries, portrait,
  canonical PCM, dimensions and frozen profile before dispatch and publication.
- Reserve actual free VRAM for the frozen dimensions and a bounded host-memory
  scope. Preserve the existing wait/idle-owned-model eviction mechanism and
  active-consumer protection. No external service may be stopped. Keep caller
  deadlines, including agent budgets; do not silently extend them for this
  slower profile.

## Complete timing and bounded geometry

The target is `ceil(samples * 25 / sample_rate)` frames. Generate
`ceil(target_frames / 2)` native base frames, preserving the recording's tail
instead of upstream's floor-before-subsampling behavior. RIFE yields `2*N-1`
frames. An even target requires one final 40-ms presentation hold; an odd target
needs none. This endpoint alignment is not an identity freeze, repeated internal
window or drift repair. Preserve all canonical audio; never use `-shortest` to
hide a missing tail. Non-integral durations may differ by less than one video
frame; source samples and provenance remain exact.

Upstream scales the shortest image side. Passing 384 blindly can create a
1536-px dimension on a 4:1 input. Freeze a 64-aligned canvas bounded by 384 px,
fit/pad the unchanged portrait into it, and revalidate natively. Do not crop or
stretch the source. The measured 2:3 profile is 256×384; a square canvas needs
a larger admitted memory budget and separate qualification. Do not present the
rectangle's shared-GPU measurement as proof of every geometry's fit.

`whole_avatar_timing.py` starts these pure boundary contracts without importing
inference dependencies or marking an executor available. Native model Python
also imports it, so it remains Python 3.10 compatible.

## UX and acceptance

Keep portrait and speech primary. A clear quality choice should identify the
stable whole-recording behavior and its higher compute time, without technical
paths, inference graphs or another Chat/Work mode. Only tested/configured profiles
appear operational. Preserve histories and source lineage in Library and Runs.

Before promotion, test legacy serialization, frozen observations, exact TTS
handoff, reviewed-agent scope, source/path/hash/permission rejection, odd/even and
non-integral timing, bounded geometry, GPU wait, Stop before/live dispatch,
deadline, lost replies, recovery, resource release and no partial publication.
Then qualify the actual full-duration manual and agent/browser paths, original
sources, complete speech, motion, eyes/color throughout and final Library output.
Run local gates, review the complete PR to develop, deploy and truly retest.

The frozen v15 AVATAR-005 explicitly describes the old 384-px/8-step Echo profile.
Do not silently record a 25-step Sonic experiment as that exact retest, change
its issued definition or mark QA-020 fixed merely because a private video looks
better. Preserve the old failure and explicitly bind any replacement acceptance
profile to the actual repaired deployed behavior. The QA goal remains open.
