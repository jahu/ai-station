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

The owner subsequently judged the face improved overall but still too soft,
closer to 240p than HD. That is a rejection of final sharpness, not permission to
promote the low-resolution result. An actual **512×768, 25-step, two-second**
comparison then completed in **598.80 seconds**, peaking at **5,719,515,136 bytes**
of allocated VRAM. Its first/last samples retain more source skin and eye detail.
The exact original LLM profile was restored afterward. This is still below a
720-pixel short side and does not qualify a complete higher-resolution workflow.
The same two-second 512×768/25-step profile also completed with both discovered
GPUs in **417.25 seconds**, versus 598.80 seconds on one: about **30% less elapsed
time**. Independent guidance branches retain the complete 25-frame attention
context. Allocated peaks were **9,439,037,440** and **5,456,757,248 bytes**. This is
neither a twofold speed claim nor qualification of a larger square canvas or a
40-second high-resolution recording. Decoded single/dual comparisons measured
SSIM 0.9881 over the frame and 0.9832 in the face crop; they are not bit-identical.
The original managed llama.cpp profile was restored through the typed API.
An existing RealESRGAN image Run also produced a sharper **1024×1536** comparison
frame from the 256×384 movie; this is explicitly upscaled, not native HD, and
temporal consistency has not been verified. Compare native detail and finishing
on short motion before another costly full-duration run. Do not call a larger
container, CSS enlargement or an unreviewed upscale a sharpness fix.

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
1536-px dimension on a 4:1 input. Freeze an explicit 64-aligned resolution canvas,
fit/pad the unchanged portrait into it, and revalidate natively. Do not crop or
stretch the source. The measured 2:3 profile is 256×384; a square canvas needs
a larger admitted memory budget and separate qualification. Do not present the
rectangle's shared-GPU measurement as proof of every geometry's fit. The helper
requires the caller to provide a 384- or 768-pixel bound explicitly; it does not
silently select the rejected smaller profile. A 2:3 canvas with the larger bound
is 512×768 and retains the reference portrait's native dimensions in this QA.

`whole_avatar_timing.py` starts these pure boundary contracts without importing
inference dependencies or marking an executor available. Native model Python
also imports it, so it remains Python 3.10 compatible.

## Native qualification implementation

The owned `sonic_entry.py` and its internal typed launcher now implement the
next qualification boundary. They are **not exposed by an HTTP route or advertised
as an available executor**. `AI_STATION_REAL_GPU_TESTS=1` and a matching, actual
18-GiB/zero-swap user scope are mandatory before model imports. The scope retains
ProcessManager PID/group ownership and a four-hour maximum; a shorter absolute
caller deadline is never extended. Existing memory profiles retain their exact
one-hour fuse and serialization.

The launcher binds canonical portrait/PCM observations, permissions, exact
installed-source/weight/adapter hashes, seed and allocated GPU identities. A lost
reply inspects the same journal and frozen receipt; unknown work is not replayed.
Only configuration supplies runtime/Python/model paths. No caller commands,
graphs, inference code or weight paths are accepted. The current resolution
qualification ceiling is 512×768 pixels of area within the explicit 768-px bound;
a 768×768 request is rejected pending a separate resource qualification.

The fixed native entry uses upstream audio preparation without replacing its
conditioning or diffusion math. Capturing the actual pipeline arguments avoids
the upstream helper's final whole-movie CPU→GPU→CPU copy. Normalization mutates
the sole decoded CPU buffer; interpolation/encoding holds neighboring frames
rather than a second complete rendered movie. The single-GPU variant serializes
three independent guidance branches; the two-GPU variant scatters those branches
while preserving each full temporal context. RIFE weights load strictly with
`weights_only=True`. Source files and existing environments remain unchanged.

Full decoded frame timestamps, dimensions, audio duration and decoded speech
sample count gate atomic publication. Partial output remains in the owned work
directory. No `-shortest`, audio trim, static-face replacement or independently
generated portrait windows are introduced. The production plan, resume, agent,
resource admission and UI integration described above are still outstanding;
this implementation alone does not close QA-020 or establish HD quality.

The actual new launcher/entry subsequently generated a **512×768, 50-frame,
25-fps, two-second** recording with complete speech. Its independent final
decode/source/model checks passed; the complete qualification controller took
574.85 seconds, including setup, two process-lifecycle fixtures, hashing,
generation, interpolation and verification. This is not a denoising-only timing
or a full-duration application Run. Actual 18-GiB/zero-swap scope fixtures also
confirmed owned process-group cancellation and an earlier absolute deadline;
neither left live children. Repeated dispatch returned the same owned PID.
The pre-reboot managed LLM was restored with its exact saved configuration.

Code review found that an expired deadline must still permit reconciliation of
an already-owned dispatch whose reply was lost. The corrected launcher inspects
an identical frozen receipt/journal after expiry while rejecting fresh expired
or unbounded dispatches before creating any work. Three regression cases cover
this distinction. The complete 4608-case normal collection passed on the native
qualification head (4599 passed, nine ordinary opt-in skips); the final affected
189-case family and global Python lint/format checks passed after the review fix.
No inference implementation changed in that fix. The HTTP/application/agent/UI
and high-resolution full-duration gates above remain outstanding.

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
