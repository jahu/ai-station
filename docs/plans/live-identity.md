# Live identity — experimental face and voice conversion

Requested 2026-11-14. Deliver a new **Live** workspace: choose a portrait and a
voice recording, start the browser camera/microphone and see/hear the transformed
stream. This is a live session, not an uploaded-video render. Existing Chat,
Images, Video, Audio and Avatars remain unchanged.

## Delivery and acceptance

1. Qualify real face and streaming voice engines on the available machine before
   marking them available. Candidate: ONNX identity swap with a single portrait;
   Seed-VC tiny streaming conversion with a short reference recording, no speaker
   training. Freeze sources, hashes, dependency versions and licenses. Measure
   sustained frame rate, audio real-time factor, latency, VRAM/RAM and drift.
2. Reuse guided, administrator-owned preparation and model/resource registration.
   Keep inference in a dedicated native owned process with a fixed engine/profile.
   No arbitrary commands, checkpoint URLs or SDK paths in browser requests.
3. A session is one ordinary Task/Run. Workers reserve resources, dispatch,
   heartbeat and inspect it. Start only after references, readiness and permissions
   are checked. Capture comes from the user's browser, not a host camera daemon.
   Start/Stop and interruption must retain ordinary ownership and recovery rules.
4. Use a bounded bidirectional media transport. This is a genuine WebSocket use
   case; keep SSE for ordinary events. The authenticated control plane proxies to
   the typed private Runner transport. Recheck session ownership, origin and account
   revocation throughout a stream; close DB scopes before waiting for media.
5. Live UI: portrait and voice selectors with uploads/Library, device choices,
   large transformed preview, optional local input preview, microphone/output
   meters, explicit monitoring, readiness, measured performance and clear Stop.
   Browser camera/mic need localhost or HTTPS (including the private Tailscale
   address); ordinary HTTP LAN access must explain how to open a secure address.
6. Keep one frozen target identity and voice conditioning for the complete session.
   Do not infer a different speaker independently for each audio chunk. Crossfade
   chunk joins. Align video presentation to converted-audio timestamps; bound
   queues and latency rather than accumulating minutes of stale frames.
7. Fail closed: failed/absent/ambiguous face tracking must not expose an unchanged
   original face as a successful transformed frame. Voice failure mutes/stops
   transformed output rather than passing the original microphone through.
   Report failure/overload and allow a deliberate restart. Do not label passthrough
   or sample replay as successful real inference.
8. Closing the tab/disconnecting must release the owned inference process and GPU
   reservations after a short bounded reconnect allowance. Worker or Runner loss
   must not silently reopen capture, duplicate a session or reserve devices forever.
9. Do not persist live frames or raw microphone samples by default. Retain references,
   settings, lifecycle, performance summary and errors in normal private history.
   Any future recording is an explicit action producing a normal Library artifact.
10. Verify fake transports, owner isolation, malformed/oversized/rate-limited input,
    account revocation, cancellation and recovery; then actual sustained GPU audio
    and video processing, A/V alignment and browser device permission behaviour.
    Clearly separate synthetic-camera qualification from a user's physical webcam.

## Model/implementation investigation

- [Seed-VC upstream](https://github.com/Plachtaa/seed-vc), pinned investigation
  revision `51383efd921027683c89e5348211d93ff12ac2a8`, documents reference-based
  streaming and RTX3060 Laptop measurements. Its code is GPL-3.0; treat it as a
  separately licensed external component, not copied into the core application.
- [Seed-VC Realtime](https://github.com/jiaheguo521/seed-vc-realtime), investigated
  revision `58d0ca372cc76f60a798d9f84611f053f9029f3a`, separates its engine from the
  GUI and documents buffering/underrun fixes. Audio-device-specific estimates do
  not prove browser network latency; measure that separately.
- [RT-VC](https://github.com/Berkeley-Speech-Group/RT-VC), investigated revision
  `9d9a55d0fb6cd53ebba108a0bab3380b1fc3c066`, currently has only a short project
  README and no usable installation/license contract in the inspected entry
  points. Do not select it merely from the paper's latency figures.
- [FaceFusion model assets](https://github.com/facefusion/facefusion-assets/releases/tag/models-3.0.0)
  provide the candidate ONNX swap/recognition weights. Model rights are separate
  from code rights; show actual licenses in preparation. No automatic training,
  hardware/driver changes or unreviewed public showcase exports.

## Scope and cleanup

The first target is the existing Linux NVIDIA workstation and private browser
access, with dynamic GPU selection. Measure single/shared versus separate GPU
admission before fixing a profile. Do not claim Windows GPU or virtual-device
integration from Linux/browser tests. OBS/Zoom virtual-camera/microphone export is
an extension, not a substitute for a working in-platform live preview.

Reuse existing dependency caches read-only and create one owned qualification
runtime, not an environment per experiment. Keep concise hashes, timings and
short neutral samples; remove superseded candidate weights/SDKs at task close.
Only independent verified production inputs may outlive qualification.

## Initial measured qualification

On the existing dual-RTX3060 Linux workstation, real CUDA face inference
completed 150 repeated 512×512 frames at 18.14 fps (54.98 ms median, 57.38 ms p95).
ONNX profiling recorded 39,411 CUDA kernel events; provider presence alone was not
used as proof. No-face input raised a tracking error without returning the input.
A CUDA-graph experiment changed throughput only slightly and was not retained.
This is a fixed-frame baseline, not yet a physical-camera/motion acceptance test.

Real offline Seed-VC conversion processed a ten-second recorded source as 50
consecutive 200-ms blocks. At six diffusion steps, processing was 125.82 ms median,
141.15 ms p95 (real-time factor 0.637), with about 920 MiB peak allocated tensor
memory. The same target conditioning and session seed were retained. This excludes
browser capture, transport and playback latency. Host sound-device access was
explicitly disabled: browser PCM must not require PortAudio or a host microphone.
The real FSMN VAD and conversion models ran; no model output was simulated.

## Session implementation and integrated qualification

The implementation on develop contains the fixed offline recipe (118 verified inputs),
owned preparation over the existing setup worker, closed native session dispatch,
separate face/voice children, a bounded private Unix media broker, authenticated
WebSocket proxies, the shared HostMediaExecutor adapter and the Live workspace.
Browser audio uses an AudioWorklet with fixed 200-ms PCM blocks; converted-video
presentation follows its audio clock. Neither live camera frames nor microphone
blocks are persisted. Voice references and conditioning are sealed memory files.

The profile requires Linux x86-64, CUDA-13-compatible drivers and NVIDIA compute
capability 7.5 or newer. Each enabled medium reserves one distinct GPU (at least
4 GiB total VRAM), and the session reserves a 12-GiB, zero-swap host-memory scope.
The workstation needs at least 16 GiB system RAM. Busy VRAM waits through ordinary
resource admission; external processes are never stopped. This initial profile
qualifies separate GPUs for simultaneous face and voice, not shared-GPU inference.

A fresh fixed-runtime assembly passed hash verification, four reproducible
pure-Python source builds, offline wheel installation, dependency checks and
imports. A second installation completed through an actual administrator-owned
Task/Run, native preparation and activation in an isolated QA station.

With both real engines in the prepared runtime, a ten-second duplex stream
returned all 50 consecutive audio blocks and 146 of 150 camera frames. Face p95
was 61.76 ms and voice p95 137.61 ms per 200-ms block. The latest-frame camera
queue intentionally discards stale input rather than delaying the whole stream.
Disconnect stopped both children and returned GPU memory to the prior baseline.

A Chrome synthetic-camera/microphone test completed Library selection, ordinary
Run dispatch, converted preview and explicit Stop without JavaScript errors. It
measured roughly 563 ms preview delay. Its initial 6.7-fps browser pacing exposed
an avoidable timer skip; acknowledgement-driven pacing replaces that delay and
has a regression test. The frozen default-gate build then measured 10.5 fps,
64-ms face processing, 140-ms voice processing per block and 544-ms preview delay
under concurrent regression load. Stop again canceled the owned Run without
JavaScript errors.
These are real model tests with synthetic capture devices, not a physical-webcam
or phone acceptance claim. Screenshots and short test outputs remain private.

The private Runner's existing platform admission dependency now accepts an
HTTPConnection, so the same platform policy covers HTTP and WebSocket routes.
Linux accepts the qualified duplex transport; Mac/unknown platforms refuse it.
Lost start replies inspect the original native journal. A pre-dispatch Stop
fences late starts. Lost workers resume inspection rather than camera capture;
revoked accounts can only stop their original owned process through trusted
coordination. Unknown dispatches retain reservations until a native Stop fence
is confirmed. First attachment must arrive within 15 seconds of readiness;
loss of media ends the session within five seconds. The UI defaults to a
30-minute session, unmonitored voice output and hidden local input.

The complete Python regression ran in four file shards: 10,297 tests passed on
the first pass. Three source-fingerprint checks raced ongoing edits; all affected
transport/launcher checks passed on the frozen head without changing their
assertions. Supplementary current Live/account/recovery/platform tests also passed.
The full frontend suite passed 1,286 tests, with the later pacing test separately
verified; lint, typecheck, formatting, production build, Docker image and both
Compose variants passed.

## Delivered on develop and local deployment

PR #783 was reviewed and squash-merged to develop at
`a3b64e6c28192cd0aba3e78aaa4cda1b59c71fc4`. The immutable local production
checkout and image use that reviewed application source. The preserving upgrade
backed up and checked SQLite first, retained the existing LAN bindings, private
Tailscale service and search container, and passed API/Runner health checks.
Stable 0.7.0 release artifacts were not changed.

The production runtime was prepared by the ordinary worker/native setup flow:
Run `f6b3eddc-d5bd-475e-8640-8c5a93d39100` succeeded. A temporary non-admin
account then exercised the real production UI with synthetic camera/microphone:
Library references, device capture, converted preview and Stop. Localhost measured
9.7 fps, 68-ms face processing, 139-ms voice processing per 200-ms block and
544-ms preview delay. The same flow passed through the existing private
Tailscale HTTPS service and WebSocket transport: 9.3 fps, 66-ms face processing,
136-ms voice processing and 544-ms preview delay. Both Runs ended canceled with
confirmed process exit and no JavaScript errors. HTTPS certificate verification
remained enabled; no public listener, Funnel or OS networking changes were added.

The temporary account was disabled, its sessions revoked and generated credential
removed. All isolated QA service processes had exited. The temporary loopback
transport probe was stopped. After checking processes/open files, container and
service configuration, database references, active-runtime links and Python path
files, task cleanup removed duplicate qualification models/SDKs/environments,
the isolated QA station, temporary wheel builds/capture fixtures and the obsolete
unregistered component-qualification runtime/identity. Filesystem free space
increased by **21.08 GiB**, measured before/after cleanup. Installed model inputs
and the active runtime are retained. Private concise evidence has a 30-day review
period; the 0.7.0 image/source and checked database backup remain rollback inputs
until the next qualified release. No unrelated models, shared environments or
virtual machines were removed.

Status: the requested experimental in-platform Live workspace is implemented,
reviewed, locally deployed and qualified with real models and synthetic browser
devices, including private HTTPS/WSS. Physical webcam/microphone, phone capture
and subjective face/voice quality remain explicit user acceptance tests. OBS/Zoom
virtual-device export and Windows GPU qualification are separate extensions;
these Linux measurements do not claim them. No live recording is enabled.

## Owner acceptance and next release — 2026-11-15

The owner tested Live and reported that it works very well, then explicitly
requested inclusion in the next release. Keep the existing qualified face/voice
profile in that release's scope; its implementation is committed in PR #783 and
final deployment/cleanup evidence in #784. This records qualitative owner feedback,
not a claim that every device/network/browser acceptance case was completed.
Release promotion and publishing still follow the normal owner-approved master
workflow; do not move the existing 0.7.0 tag.

The owner also observed retained hair and skin characteristics. The current
engine transforms a 128-pixel aligned face crop and blends it into the original
frame with a soft elliptical mask; hair, neck, ears outside the mask and the
background are not replaced. A wider mask alone cannot synthesize the reference
person's hair or unseen head geometry.

A separate future full-portrait mode should investigate reference-portrait
animation driven by webcam motion, rather than widening this face-swap mask.
[LivePortrait](https://github.com/KlingAIResearch/LivePortrait) provides a relevant
source-image/driving-video architecture; its documented head-focused framing and
motion constraints must remain visible in evaluation. Benchmark a real streaming
adapter on the actual GPUs before promising frame rate, resolution, full-head
coverage or concurrent voice performance. Include turns/profile views, hairline,
neck/skin consistency, occlusions and fail-closed tracking in that qualification.
Keep the working face-swap profile available independently. No new engine, weights
or changed defaults are installed by this acceptance note.


## Active implementation: animated reference portrait — 2026-11-15

Add an explicit `portrait` mode beside the existing default `face_swap`. The
portrait is the rendered appearance source (including its hair/head/skin), while
the browser camera supplies motion and expression. Never composite webcam pixels
into this mode. Keep ordinary Task/Run history, resource locks, sealed references,
bounded binary transport, Stop, revocation and crash recovery. Existing requests
without a mode and frozen old runtimes retain face-swap behaviour.

Qualify a pinned MIT LivePortrait human model/SDK in an optional fixed runtime,
with actual CUDA inference before advertising availability. Reuse the verified
Live Python/dependency inputs and independent voice process, avoiding additional
large qualification environments. Closed mode/runtime validation must reject
mismatches. The UI explains both choices, requires an image for portrait mode,
shows its own preparation readiness, and freezes mode during capture.

Measure real motion transfer and reference appearance retention, tracking loss
and multiple faces, GPU/RAM use and end-to-end browser A/V pacing. Test default
compatibility, cancellation, account isolation and setup/recovery routing. Deploy
only after review and local checks; retain the working face-swap runtime. Remove
owned probes and duplicate SDK/model/environment copies at completion.


### Animated-portrait implementation qualification

The pinned human LivePortrait SDK uses only its reviewed model classes and
configuration. Five weights load with `weights_only=True` and strict state
dictionaries in the existing qualified Live Python. The extension downloads
522,362,364 bytes of model/SDK inputs and binds an immutable base-runtime
observation; switching the base active pointer does not retarget an existing
extension. Empty upstream package initializers are omitted: namespace packages
need no zero-byte downloads, and every downloadable object satisfies FileSpec.

The initial real CUDA qualification on the dual-RTX3060 workstation rendered
60 measured 512×512 frames at 6.72 fps (148.22-ms median, 155.35-ms p95), with
about 1,057 MiB peak allocated tensors. Rotated driving inputs changed the
rendered portrait while retaining its reference appearance. Missing faces refused
output. A ten-second actual dual-GPU stream returned 65 portrait frames and all
50 audio blocks, portrait p95 157.54 ms, voice p95 134.42 ms, and exit 75 on
disconnect. Latest-frame dropping bounded the queue; no raw-camera fallback was
used. This is an experimental portrait profile, not a 25/30-fps claim.

An isolated station prepared the extension through normal setup Run
`742ab92b-8a28-49c6-87db-cd4820fa6f74`, then ran an ordinary portrait session
with synthetic Chrome camera/microphone. Desktop/mobile layout, reference
selection, converted preview and Stop passed with no JavaScript errors. Under
concurrent regression load the UI reported 5.3 fps, 161-ms portrait processing,
137-ms voice blocks and 555-ms preview delay. Stop canceled the owned Run and
confirmed process exit. These are real models with synthetic devices; physical
camera and subjective motion quality are still user acceptance.

A further pinned real driving-video check rendered all 48 sampled frames, with
no tracking pauses. Visual inspection confirmed transferred gaze, mouth opening,
smiles and eye closure while keeping the reference hair, head and background.
This complements the rotated-image throughput fixture. New model links are
relative to the data root; the runtime retains its explicit original base binding.

Final regression review, production adoption and cleanup are delivery gates
remaining for this extension. The existing face-swap deployment remains intact.
