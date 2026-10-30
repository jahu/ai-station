# Expressive speech (NR-06)

Preserve the installed Polish Chatterbox Multilingual V3 path and exact narration.
The inspected `clone_pl.py` already accepts `--exaggeration`, `--cfg` and
`--temperature`, but the application currently passes none of them. Expose these
real controls through optional bounded delivery settings. Requests without them
retain the existing CLI arguments, identities, chunking and runtime defaults.

Keep speech under the ordinary Task/Run, resource admission, owned process group,
deadline, cancellation and complete-file publication. Each chunk receives the
same frozen delivery settings. Record settings and the inspected CLI hash on the
Run and output. A changed or incompatible CLI must reject the controlled request;
never add unrecognized flags or silently drop requested controls. Capability
inspection reads configured source without importing models or starting Python.

The workspace offers expression and, under advanced settings, guidance and
variation. Saved sessions/versions restore those settings. These controls are
not named emotions and do not claim reliable whispering or inline sound effects.
The original voice reference remains important. Compare real neutral Polish
auditions before claiming improved naturalness or making a new default.

The remaining NR-06 target needs a qualified instruction-controlled voice model
for explicit whispering, sadness, happiness, fear and other delivery changes.
Evaluate [Fish S2 Pro](https://huggingface.co/fishaudio/s2-pro), whose model card
documents Polish and inline directions; retain its separate model license.
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) is another supported-language
candidate, not a Polish replacement. Do not install or modify another application's
environment. Use an app-owned runtime, verified weights, actual VRAM measurement,
short complete-word auditions and cancellation/recovery qualification before
advertising an adapter as available.

Implementation/qualification of existing controls is one step toward NR-06;
it does not complete that requirement or the full 0.1.0 release.

## Qualification recorded 2026-10-30

The existing-controls candidate passes short/complete chunked speech, exact text,
frozen source checks, unsupported-runtime rejection and cancellation for both
single-call and chunked controlled speech. Account-bound creative versions retain
the controls and deny another user's history/file access. Compiled desktop/mobile
checks use a real private API, separate worker and native synthetic CLI; the form,
saved continuation and actual dispatched settings pass without GPU inference.

Separately, the installed Chatterbox V3 generated standard, restrained and
expressive Polish samples through an isolated actual API/worker/native pipeline.
Measured generation was 36.35, 27.54 and 28.98 seconds, respectively; peak allocated
VRAM was 3.39 GiB in all three. Every WAV decoded; offline CPU Whisper recognized
the passages with minor deviations. These are intelligibility observations, not
human listening acceptance or proof of specific emotions. Defaults remain unchanged.
Private evidence is under `data/acceptance/expressive-speech-20261030/`.

## Fish candidate: measured profile and remaining integration

The complete S2 Pro download is verified against the publisher's SHA-256 values,
revision `1de9996b6be38b745688de084d87a5633f714e4e`. The isolated runtime uses
Fish Speech code `0f8a12e8a651062fdee9c33a894bdccd3a8513f1`, Torch 2.8/CUDA 12.6
and a reproducible dependency record. TensorBoard 2.19 is needed alongside the
upstream protobuf constraint; the newer resolved version failed codec import.
No external application's environment, source or model was modified.

A real one-GPU BF16 load ran out of VRAM when transferring codec buffers. The
accepted execution candidate instead places the semantic model on one GPU and
the codec on another: about **9.18 GiB** and **4.16 GiB** peak allocations on the
two RTX 3060 cards. All model/codec parameters stay on GPUs; there is no CPU
offload. The upstream loader's existing `max_length=4096` bounds the context/cache,
and a 512-semantic-frame limit bounds this short qualification. These are profile
requirements, not a claim that an 11-GB file fits an arbitrary 12-GB device.

Using the same synthetic Polish reference and exact recorded reference text,
neutral, `[whispering]` and `[happy]` passages produced complete decoded WAVs in
about 11 seconds each after loading. Offline CPU Whisper recognized their wording
with minor deviations. This is standalone GPU qualification, not a working AI
Station adapter, human listening acceptance or long-form qualification.

The next implementation must reuse the existing media executor lifecycle:

- Add an optional typed speech-engine/direction choice; keep legacy Chatterbox
  request serialization and ordinary narration unchanged.
- Use the owned reference's verified spoken text when available. For an uploaded
  voice, prepare its transcript with the existing offline transcription Run;
  never ask users to transcribe a reference manually or invent reference words.
- Freeze the verified runtime/weight profile, reference bytes/text and direction
  before the normal Fish Run. Native code accepts fixed data and configured
  paths, never caller-selected Python, flags, model repositories or commands.
- Reserve both discovered GPUs and bounded load RAM through existing admission,
  retaining the fixed zero-swap process scope. Allow arbitrary discovered GPU IDs;
  do not assume the workstation's indices in application code.
- Generate bounded complete passages, verify EOS/PCM/duration and retain stems
  before publishing a complete result. Preserve Stop, owned process inspection,
  deadlines and inspect-before-retry recovery; do not silently truncate a script.
- Show the model license and Built with Fish Audio attribution for this optional
  engine. Keep it unavailable until configured and its permission, cancellation,
  recovery, private history and fake/real integration contracts pass.

The public workspace should offer a model choice and plain-language delivery
directions. A per-version advanced panel can hold sampling controls; a user
should not need paths, GPU topology or inline model syntax to request a whisper.
Longer speech, sadness/fear and actual audible delivery remain qualification work.
