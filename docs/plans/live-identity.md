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

Closed packet framing and face-tracking failure tests currently pass 28 cases.
Normal tests load no GPU model or optional inference dependencies. Full session
transport, resource/recovery/privacy checks and Live UI remain to be implemented.

Status: implementation in progress; no session adapter or UI is reported
operational yet. This plan is not a completed feature.
