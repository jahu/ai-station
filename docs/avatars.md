# Local avatar video

## Optional stable-detail engine

The configured Sonic integration animates the whole recording in one Run and
keeps the original portrait proportions, up to a 768-pixel side and 512×768
pixel-area budget. Avatars offers portrait + recording or voice reference + new
spoken text, real generation progress, Stop, explicit Resume and a final Library
film. Reviewed avatar agents use the same pipeline; existing saved Echo settings
are preserved. See the [whole-recording plan](plans/whole-recording-avatars.md).

It is **disabled by default**. Configure `AI_STATION_SONIC_PYTHON`,
`AI_STATION_SONIC_DIR`, `AI_STATION_SONIC_MODELS` and explicitly enable
`AI_STATION_SONIC_WHOLE_ENABLED` on the native Runner. Readiness verifies existing
offline files; it never downloads weights or starts inference. An initial hash
check reports checking. GPU discovery and owned user memory scopes are required.
Manual full-detail jobs permit four hours; reviewed agents keep their own limit.
Detailed rendering can take hours. The real complete 40.08-second application
recording passed full decode, canonical audio, hash and Library/browser checks at
native 512×768/25 fps. A separate two-second agent journey also passed. The
[quality follow-up](qa/whole-avatar-follow-up.md) records the owner's confirmation
of substantially improved quality and retains the original Echo failure (QA-020). This is
not an HD or perfect-identity claim. The controlled workstation preview now uses
this profile for new requests; existing Echo histories retain their settings.

During animation, the workspace estimates remaining animation time from saved
progress events after at least three measured windows. Model preparation is
excluded; saving and final verification follow that estimate. Refreshing the
browser retains the measurement. Queued, stopped, finishing or stale progress
has no countdown. This is a read-only projection, never authority to complete,
retry or extend a Run. The estimate uses observed speed rather than a fixed GPU
benchmark.

## Existing Echo engine

The current workspace defaults to **Full recording (up to 60 seconds)** through
[durable long-media jobs](long-media.md). Generated speech uses the same complete
recording plan; bounded motion windows share one canonical audio timeline. The
[latest full-minute qualification](plans/platform-acceptance-audit.md) uses
1500 frames at 25 fps, 384-square/eight steps and `portrait_anchor_v1`: 24 native
windows plus composition, all 23 joins sampled and full desktop playback/mobile
ending checked. The complete input recording is retained with zero observed
audio lag and 0.9991 correlation. Contrast/color and facial-detail drift remain
visible; this is not perfect-identity or exact lip-sync qualification.

The minute fixture is an explicit 60-second recording excerpt of fresh
62.44-second local narration, with no loops, stretching or silent padding.
It does not claim the uncut TTS text's ending inside that excerpt. A separate
36.52-second workflow verifies the complete shorter speech-to-avatar chain.
Evidence: `data/acceptance/avatar-full-minute-20261026/qualification-complete.json`.
The [earlier 30-second timing/playback record](long-avatar-qualification.md#executed-2026-10-15)
remains historical; it is not the current whole-narration quality proof.

Operator visual acceptance on 2026-10-28 reports progressive eye/facial
deformation (QA-020). That historical quality failure remains open despite its
successful timing/playback checks. The subsequent
[controlled engine comparison](plans/avatar-model-quality-evaluation.md) led to
the optional whole-recording Sonic integration described above; its complete
512×768 output received positive overall quality feedback from the owner.

The direct short-Run adapter and earlier verification below remain compatible;
their per-window frame limits are not the current workspace's duration limit.

Avatars and Video expose the same concrete capability: EchoMimic V3 portrait animation driven by an existing speech recording. This is not a text-to-video model. The default assistant can also dispatch it when a portrait and WAV are attached, or when the avatar action is selected.

`avatar.animate` creates an ordinary Task/Run through `echomimic` and the shared HostMediaExecutor. It reserves one discovered GPU, can evict idle AI Station-owned LLMs, streams logs, cancels only its owned process group, and preserves uncertain work for inspection. Outputs are MP4 video Artifacts with the portrait and audio as parents; Library, Avatars results and the assistant inspect that shared lineage in both directions. Inputs reuse the validated image and PCM WAV upload endpoints. The initial controls bound area to 256/384/512 squared, 17–81 frames at 25 fps, 4–30 steps and an explicit seed. The source aspect ratio and shorter audio duration are preserved by the installed pipeline.

Configure the native Runner with `AI_STATION_ECHOMIMIC_PYTHON`, `AI_STATION_ECHOMIMIC_DIR` (containing infer_flash.py and config/config.yaml), and `AI_STATION_ECHOMIMIC_MODELS` (the existing flash directory containing Wan2.1-Fun-V1.1-1.3B-InP, transformer and chinese-wav2vec2-base). No models are downloaded. Models and the existing installation are left unchanged.

The Runner launches its small `echomimic_entry.py` adapter using the configured external Python environment. It imports the installed inference entry point and substitutes a pipeline subclass whose device-placement method enables sequential CPU offload once. This implements the memory mode declared but unused by the inspected infer_flash.py, avoiding loading every component into VRAM together. No installed source is rewritten. All outputs, temporary mux files and caches use a new application-owned run directory. The adapter decodes the result and verifies an audio track before publishing the UUID-based MP4.

Real installation probe (2026-09-28): existing offline weights and CPU offload generated a 17-frame portrait video at 256-square area with four diffusion steps, using a locally generated Chatterbox WAV. Application/browser acceptance is recorded separately after verification.

Real application/browser acceptance: Run `176feb52-0057-464e-9af5-5d52b17430cd` completed through upload → queued worker → native EchoMimic → video Artifact → browser playback. The 0.68-second result decoded at 256×240 with audio; GPU locks were released and no browser JavaScript errors occurred. The Video workspace route also passed. Cancellation, symlink rejection, permissions, output reuse rejection and assistant child dispatch passed fake-executor integration tests.

The media workspace keeps portrait/audio previews and video output together. Existing inputs can be searched and selected from Library. Images, Audio and Library can stage a portrait (`?image=`) or WAV (`?audio=`) into Avatars without queueing a Run; the composer remounts on those sources, not when a generation Run is recorded in the URL. Each inline picker is one keyboard sequence (arrows, Home, End, Enter attaches) with unique Choose names. Quality and clip length are primary controls; steps, seed and GPU are under Advanced settings. Those Quality and Clip length radios reuse the shared list keyboard with unique Quality and Clip names; Space or Enter selects a row and does not queue an avatar Run. There is no inspectable quality or clip-length Run. The GPU target radios reuse the shared list keyboard with unique Target GPU names; Space or Enter selects a row and does not queue an avatar Run. There is no inspectable GPU-target Run. Generation, cancellation and playback remain in the workspace, with Run/log and Library links for deeper inspection. Desktop and narrow-screen layouts were checked in a real browser, including restored playback from a completed Run URL.

Portraits can now use a voice reference and typed Polish speech through a sequential Chatterbox → EchoMimic workflow, retaining both outputs and following the active stage after refresh. See [speaking avatars](speaking-avatars.md).
