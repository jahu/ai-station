# Synchronized scene sound (NR-07), then timeline editing (NR-08)

Owner request: describe the sound of a film and obtain actual synchronized local
sound effects/ambience, with a later editable multitrack film. Speech, music and
effects remain separate stems and capabilities. This is not satisfied by adding
music to a silent video or by exposing an unqualified model selector.

## Selected candidate and current evidence

[MMAudio](https://github.com/hkchengrex/MMAudio) generates audio conditioned on
video and text. Source is pinned for qualification at
`974010a026c731054592d8f777218bd9d85a6c24` (MIT code); the
[publisher checkpoints](https://huggingface.co/hkchengrex/MMAudio) are separately
CC BY-NC 4.0. The first candidate is `large_44k_v2`, BF16, one discovered CUDA GPU.
Its actual VRAM/RAM consumption is not yet measured here; do not advertise it as
ready based on file size or the authors' hardware measurements.

The independently installed, project-owned runtime is separate from Fish,
Chatterbox, the control-plane image and existing user model trees. Public assets
are downloaded at immutable revisions and checked against publisher SHA-256 (LFS)
or Git blob identities (small configuration files). Required inference assets:

- MMAudio flow model, 44-kHz VAE and Synchformer at checkpoint revision
  `eb13a1a98fdbec91753775c57b074ccdfc60587c`.
- CLIP config/weights at `01b771ed0d1395ca5ffdd279897d665ebe00dfd2`.
  The upstream `apple/DFN5B-CLIP-ViT-H-14-384` URL redirects to the `378` name;
  retain the explicitly verified revision and make offline resolution match the
  upstream import. Do not silently follow a new model during execution.
- NVIDIA BigVGAN config/generator at
  `95a9d1dcb12906c03edd938d77b9333d6ded7dfb`.

The upstream demo downloads automatically, has unsafe prompt-derived filenames
and can truncate conditioning duration. Do not invoke it as the public adapter.
Use its inspected inference functions inside a fixed owned wrapper with offline
resolution, UUID-derived paths and independently verified timing. Do not modify
upstream source to make a model fit. Private download/runtime/qualification
records belong under `data/acceptance/synchronized-sound-20261030/`.

## Qualification before activation

Use a neutral short film already owned by QA, plus a repeatable moving-object
fixture with a visible timed action. Check real video+text conditioning, complete
finite stereo PCM, source frame coverage, sample count and actual peak VRAM/RAM.
Compare appropriate prompts (e.g. water, footsteps, wind) without claiming that
successful decoding proves perceptual synchronization. Use a real zero-swap owned
memory scope, and measure the profile before selecting its RAM/VRAM admission
limits. Never evict an external runtime or use CPU weight offload implicitly.
Exercise Stop during model loading/generation, process inspection after lost
acknowledgement and absence of published partial output.

## Shared execution contract

Add a typed `audio.effects` request with an owned video artifact, sound
instructions, negative prompt, bounded sampler settings/seed and GPU selection.
The request accepts no command, graph, model path, URL or arbitrary filter syntax.
An API handler freezes same-owner inputs and enqueues an ordinary Task/Run.
The worker reserves measured resources and dispatches a fixed native operation;
Run parameters freeze source/weight/wrapper observations and timing. Inspection,
leases, absolute deadline, cancellation and retry policy reuse existing services.

Freeze inspected frames, FPS, dimensions, source size/hash and exact timeline.
Start with existing verified app-generated MP4 clips at supported frame rates;
other imports must pass a real inspection Run rather than trust client metadata.
Long films use bounded windows in one owned execution, with explicit planned
window boundaries and continuity policy. Inspect the complete source, sample
conditioning at the model's actual CLIP/Synchformer rates, and bound decoding.
The final window may be padded for model conditioning, but publish precisely the
requested film's sample interval. Record this conversion; never shorten the film
or silently drop its final action. Verify the final sample count against the
source frame count using rational timing.

Publish a reusable WAV effects stem and a linked video-with-sound preview via the
existing typed compositor. Each is an ordinary Artifact with source lineage and
model/prompt/seed/timing provenance. Keep the original silent film. Existing
narration/music must remain available independently; replacement versus mixing
must be explicit. Arbitrary multitrack mixing belongs to NR-08 below.

## User experience and saved work

Add **Sound effects** beside Speech/Music in Audio. The form asks for the film
and what should be heard, with advanced controls collapsed. Show source video,
actual duration, model/local status, measured progress and honest estimates.
Offer **Add sound** from completed video/Library results and preserve the chosen
source when navigating. Reuse MediaInput/MediaResult and ordinary Stop/Run details.
A result exposes the standalone effects track and synchronized preview.

Extend the existing private creative sessions with an `effects` capability,
including a preserving Alembic migration for its database check constraint,
backend builder, frontend types/routes, drafts, feedback and saved variations.
Do not use browser-only history. Agent/assistant integration must use the same
schema/source authority and available-engine checks; no independent execution
architecture. Enable adapters only after permissions, cancellation and recovery
pass. Unconfigured candidates remain unavailable.

## Timeline handoff (NR-08)

Persist owner-scoped timeline projects and append-only revisions, with clips and
independent speech/music/effects tracks. A revision freezes artifact snapshots,
source in/out, timeline start, gain, mute and bounded fades using rational
sample/frame accounting. Trimming/moving/reordering changes a saved manifest,
not source artifacts. Provide drag controls with accessible numeric/keyboard
alternatives, preview waveforms/playhead and explicit render.

The native compositor builds a fixed validated mix/encode operation; callers
never supply FFmpeg graphs/argv. Preview and export follow the same manifest.
Check clipping, audio coverage, FPS/sample timing and cancellation; retain each
render, source lineage and prior revision. NR-07 effects must remain useful as
ordinary stems before the full editor is available.
