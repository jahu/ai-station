# Durable long video and full-speech avatars

The long-media increment adds ordinary dependent Runs to one media Task. Video
accepts 5–60 seconds with continuous motion or explicit shot cuts; Avatars defaults
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

Wan continuation conditions the next native window on seventeen preceding frames.
The overlapped frames are removed from the final timeline; each remaining frame is
newly generated. Shot mode intentionally starts fresh windows. Continuous windows
are sequential; two GPUs do not imply simultaneous execution of dependent stages.
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

A real 60-second 1280×704 continuous Wan acceptance is running in an isolated data
root on the configured workstation. Evidence is recorded in
`data/acceptance/long-media-20261014`. Until its final verification record exists,
this is an ongoing test, not a successful hardware claim. Full-avatar continuity,
lip synchronization and whole-speech hardware acceptance remain to be verified.

The longer-term design, including 120/300-second profiles, selected excerpts,
measured parallel admission and broader quality gates, remains in
[the execution plan](plans/long-media-execution.md).
