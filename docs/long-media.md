# Durable long video and full-speech avatars

The long-media increment adds ordinary dependent Runs to one media Task. Video
accepts 1–60 seconds with continuous motion or explicit shot cuts; Avatars defaults
to the whole recording (0.68–60 seconds), retaining short preview controls.
The existing short-Run URLs/endpoints remain compatible.

`POST /api/media/jobs/video` and `/avatar` require a UUID `client_request_id`.
Identical requests return the existing Task; changed input with that ID is rejected.
`GET /api/media/jobs/{task_id}` reports the selected plan revision, completed
segments and final artifact. The stages endpoint provides bounded historical Runs.
Stop persists Task cancellation and cancels its active Runs. Resume requires the
expected revision and another UUID, preserves completed prefix segments and seeds,
and inspects uncertain owned processes before creating replacement attempts.
A completed speech WAV is reused when resuming the avatar planner.

New Wan plans freeze the capability-selected continuation and guidance recipe.
The qualified plan strategy `last_frame_apg_v1` uses one preceding frame and
native `apg_v1` guidance; saved legacy
plans retain their seventeen-frame cached-latent conditioning. Recipe/source
observations are rechecked before native dispatch, never silently changed on Resume.
The overlapped frames are removed from the final timeline; each remaining frame is
newly generated. Shot mode intentionally starts fresh windows. Continuous windows
are sequential. Independent shot windows have no inter-shot dependency and can
use separately available GPUs when existing host RAM/GPU reservations admit them.
An explicit GPU choice stays on that device; one-GPU/low-RAM execution stays
serial. See [independent shot scheduling](parallel-video-shots.md).
Profile size/mtime observations protect Wan jobs from changed model files.

Avatar windows use absolute sample/frame positions at 25 fps. They retain the
original portrait identity, carry prior motion, pad the final inference window
with silence and use a fixed, proportion-preserving portrait canvas. Composition
trims exactly to the complete recording and muxes canonical audio once. Typed
speech creates a normal TTS Run followed by a planner; planner success means the
animation plan is ready, not that the movie has finished.

A typed native CPU executor streams MP4 decoding/encoding with PyAV. It checks
owned canonical paths, source sizes/hashes, codecs, dimensions, timestamps and
frame counts. Output is fully decoded and checked before publication. Audio sample
accounting permits codec padding of less than one video frame. The API accepts no
URLs, filters, codec arguments or shell commands. PyAV must exist in the configured
video Python environment; the project dev lock also includes it for normal tests.

GPU dispatch also reserves host RAM, leaving a safety margin and conservatively
subtracting other live reservations. Insufficient resources queue the Run. Owned
GPU/RAM reservations are released after confirmed termination; uncertain dispatch
requires inspection. Intermediate videos stay inspectable under their Runs but
are hidden from the default Library. The final video records source lineage.

## Verification

Normal integration tests use temporary databases, fake GPU generation and real
CPU MP4/audio composition, including exact frame counts, stop/resume, receipt
replay, continuous audio windows, complete speech and speech reuse. Native tests
cover canonical source preservation and final-window padding.

A real 60-second 1280×704 continuous Wan job passed on this workstation:
23 native segments, seventeen-frame motion carry, exact 1440-frame output, full
MP4 decode/timing validation and request replay. Evidence is recorded in
`data/acceptance/long-media-20261014/real-result.json`. This was a four-step draft
on one GPU; it does not qualify simultaneous two-GPU generation, all quality
profiles or image-conditioned long output. A real six-window, 14.2707-second recorded-speech avatar also passed complete
sample accounting, exact 357-frame/14.28-second video validation and actual browser
playback at desktop/mobile sizes. It used the 256-pixel, four-step draft profile;
this does not qualify every portrait, lip-sync quality or 30/60-second avatar profile.
Evidence is in `data/acceptance/conversational-media-20261015/live-avatar-result.json`.

The longer-term design, including 120/300-second profiles, selected excerpts,
measured parallel admission and broader quality gates, remains in
[the execution plan](plans/long-media-execution.md).

The [main conversation](conversational-media.md) now uses these same jobs for
explicit video durations and whole-speech avatars. Both conversation and workspace
Stop controls operate on the complete media Task.

[Owned motion checkpoints](wan-motion-context.md) now avoid MP4/VAE re-encoding
between Wan windows while preserving the same timeline and legacy compatibility.

Saved job URLs now restore the request's portrait/voice or scene inputs, prompt,
quality, dimensions and duration. A running job can show its latest successful
segment as a labeled partial preview; this does not replace final verification.
The same preview is available in the conversation job card. Reopening or inspecting
an input starts no new workload.

Shot progress shows actual running/queued counts and allocated GPU IDs. Final
composition and artifact lineage retain timeline order when completion is out of
order. Partial preview follows the last completed selected attempt; resume reuses
successful independent shots after a failed gap. Normal tests use fake GPU work
with real CPU MP4 composition, including simultaneous owned processes, Stop,
explicit-device/one-device/RAM serialization and ordered decoded frames.
Actual simultaneous generation is now separately qualified for two two-second,
1280×704/20-step bounded landscape shots on the two discovered GPUs. Complete
four-second composition, source order, kernel limits, cleanup and compiled
desktop/mobile playback pass. See [the exact measured profile](parallel-video-shots.md#actual-two-gpu-acceptance--2026-10-26).
This does not parallelize a continuous scene or qualify arbitrary two-GPU profiles.

A real 30-second avatar at the normal 384-pixel/eight-step settings subsequently
completed twelve windows plus composition in about 35 minutes. Full independent
decode, exact audio/video timing, all sampled joins, complete desktop playback
and mobile final playback passed. Appearance/hand artifacts remain visible with
the full-body QA input; broader close-up lip-sync/identity quality is separate.
See [the exact qualification](long-avatar-qualification.md) and local evidence
under `data/acceptance/long-avatar-default-20261015`.
