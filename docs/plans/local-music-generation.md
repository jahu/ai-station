# Local music generation

Status: implementation in progress. Music is not yet an operational capability.
Existing speech, transcription, video and avatars remain unchanged.

The next source increment contains the typed native launch, offline wrapper,
`audio.music` worker adapter, idempotent workspace requests and Audio → Music.
Focused fake-engine tests cover library publication, invalid output, owned Stop,
and recovery of a live process without replay. This is not a real music smoke.
The installer is merged in #360 with 2247 Python tests passing. Execution/UI
qualification and deployment remain separate from that installer result.

## Product flow

Audio gains a Music mode beside speech and transcription. Describe the music,
choose instrumental or provide lyrics, choose the duration, and Generate. Keep
GPU and seed under advanced settings. Progress, Stop, playback, download, Library
and return-to-Run use the existing media workspace. Chat/Work must eventually
dispatch the same typed request and show the same artifact, rather than launch
a separate generation architecture. Persistent-agent use follows the normal
reviewed tool/permission publication contract; it is not enabled by this plan.

## Selected runtime and exact setup scope

Use the official ACE-Step 1.5 turbo Python inference API, pinned to code commit
`ca1e85fe9430179831e6bc6be790c332190a3866`. The initial preset is single-sample
text-to-music without the optional 5 Hz music language model. Its required
Qwen embedding encoder is still included. The language model used by Chat
continues through the existing llama.cpp integration.

The committed [model manifest](../../config/music/ace-step-1.5-turbo.json) pins
16 files at Hugging Face revision
`19671f406d603126926c1b7e2adc169acbcade22`: turbo DiT, text encoder/tokenizer and
VAE, **6,336,680,772 bytes (6.34 GB / 5.901 GiB)**. Each file has an exact byte
count and SHA-256, including model Python code. The source/model licenses are
MIT. These public files require no account or API key.

Proposed workstation destination, separate from existing models:
`~/AI/models/audio/ace-step-1.5-turbo-19671f4`. This is an installation choice,
not an application default or a hard-coded username. No files are moved,
replaced or removed. Installation never alters drivers or host CUDA.

Review the actual file URLs, checksums, size and destination without networking
or writing any directories:

```bash
.venv/bin/python scripts/install-music-model.py \
  --destination ~/AI/models/audio/ace-step-1.5-turbo-19671f4
```

Only after explicit operator approval for these large weights:

```bash
.venv/bin/python scripts/install-music-model.py \
  --destination ~/AI/models/audio/ace-step-1.5-turbo-19671f4 --download
.venv/bin/python scripts/install-music-model.py \
  --destination ~/AI/models/audio/ace-step-1.5-turbo-19671f4 --verify
```

The downloader uses only the pinned public Hugging Face files/CDN over HTTPS,
without environment credentials or proxies. It reserves a new dedicated folder
exclusively, streams bounded downloads, checks every SHA-256 and publishes its
receipt last. Existing directories are refused. Interrupted downloads remain
explicitly incomplete; no automatic overwrite, retry or cleanup is performed.
Offline verification reads all files and requires a matching completed receipt.
Installing weights does not install a runtime or make Music available.

## Execution boundary

- Add `audio.music` Task/Run and a HostMediaExecutor adapter. HTTP only enqueues;
  workers own allocation, leases, Events and artifact publication.
- A typed native request accepts bounded caption, optional lyrics, duration,
  seed, discovered GPU and explicit filesystem read/workspace write permissions.
  It cannot supply executables, model URLs, scripts or output paths.
- Use a fresh project-owned ACE virtual environment, distinct from photo,
  Chatterbox, transcription and user Python environments. Pin/review dependencies;
  do not install upstream training/UI/vLLM extras merely for no-LM inference.
  Native configuration is `AI_STATION_MUSIC_PYTHON`,
  `AI_STATION_MUSIC_SOURCE_DIR`, and `AI_STATION_MUSIC_MODEL_DIR`; empty defaults
  keep the capability unavailable. Model and source directories must be under
  configured native allowed roots. Runtime source is hashed against the pinned
  upstream Python tree before imports. Checkpoint code from that source is
  copied only into a per-Run view, with approved data files linked read-only by
  convention; the upstream download/code-sync hooks are replaced with checks.
  Generation also rejects Python socket connection/DNS events and receives no
  inherited API tokens. No arbitrary agent-supplied Python is executed here.
- Validate the entire local checkpoint before importing its trusted model code.
  Pinned upstream initialization automatically downloads missing models and
  synchronizes Python files from its package into checkpoints. The adapter must
  prevent both behaviors: fail closed for missing files, keep approved weights
  immutable, and bind any runtime-local code copy to the reviewed code revision.
  Merely setting Hugging Face offline flags is not sufficient proof of this.
- Use a fixed wrapper/argv and private owned process group; no shell endpoint.
  Generation is offline. No model downloads during Runs. Cancel/recovery reuse
  ProcessManager and HostMediaExecutor ownership contracts.
- Start with CPU offload, no optional music LM, batch one and the turbo step
  preset. Devices are discovered; do not assume two GPUs or combine their VRAM.
  The official guide describes low-VRAM support, but actual admission/maximum
  duration/quality must be qualified on this workstation before advertising it.
  The initial conservative host-RAM reservation is 16 GiB. Existing resource
  admission, deferral and lease recovery remain authoritative; no work starts
  when that reservation cannot be satisfied.
- Output is an owned UUID PCM WAV plus actual duration/rate/channels, prompt,
  lyrics, seed, preset/revision and allocated GPU metadata. Validate full decoded
  frames in chunks; do not apply the short voice-reference 20 MiB/60 s limit to
  full-length music. Requested duration must agree with the actual output.

## Delivery and verification

1. Deliver offline setup planning/download verification with fake HTTP tests.
2. Obtain explicit approval before downloading the 6.34 GB of new weights.
3. Implement native offline wrapper, typed launch, diagnostics and queued
   capability; fake-engine tests cover permissions, paths, missing files,
   resources, malformed/truncated/short output, cancellation and recovery.
4. Implement Music workspace and Chat routing through the same Run creation,
   with no unavailable adapter advertised as working. Verify desktop/phone
   layout, request retry behavior, Stop, playback and Library lineage.
5. Run required backend/runner checks, frontend lint/typecheck/tests/build,
   Compose/image checks for deployment changes, and full PR review to develop.
6. Back up and roll out with the owned native Runner's source identity updated.
   Explicit real smoke: short instrumental, supplied lyrics, Stop, then longer
   duration only after the small profile passes. Preserve/reload the operator's
   previous managed text-model profile. A passing fake does not qualify music.

Primary references:
[inference API](https://ace-step.github.io/ACE-Step-1.5/en/INFERENCE),
[GPU guide](https://ace-step.github.io/ACE-Step-1.5/en/GPU_COMPATIBILITY),
[source](https://github.com/ace-step/ACE-Step-1.5),
[weights](https://huggingface.co/ACE-Step/Ace-Step1.5).
