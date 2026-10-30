# Expressive speech (NR-06)

Preserve the installed Polish Chatterbox Multilingual V3 path and exact narration.
The inspected `clone_pl.py` already accepts `--exaggeration`, `--cfg` and
`--temperature`, and the application exposes these
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

## Fish S2 Pro: optional integrated profile

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
with minor deviations. Those initial measurements qualify standalone generation; the integrated
qualification below additionally covers the application lifecycle. Neither
measurement substitutes for human listening acceptance.

The implementation reuses the existing media executor lifecycle:

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
Sadness/fear and actual audible delivery remain listening qualification work.


## Integrated qualification and configuration

Audio → Speech offers **Speech model**, then **Voice direction** and **Speaking
pace** when Fish is selected. Reviewed speech agents use the same controls.
Direction tags are applied inside the fixed wrapper, separately from the saved
script; every bounded chunk receives the selected direction and pace. Creative
versions restore them. Chatterbox remains the default and its legacy requests
retain their original serialized identities.

Configure only the native runner with `AI_STATION_FISH_SPEECH_ENABLED=true`,
`AI_STATION_FISH_SPEECH_PYTHON`, `AI_STATION_FISH_SPEECH_DIR` and
`AI_STATION_FISH_SPEECH_MODELS`. Use the pinned revisions above, an isolated
Python 3.12 environment with Torch 2.8/CUDA 12.6, the upstream dependencies and
TensorBoard 2.19/protobuf 5.29.6. Runtime installation is separate from the control
plane image. No automatic download or modification of another application occurs.
An absent, changed or still-verifying installation appears unavailable/checking.
The shipped profile requires two BF16-capable CUDA GPUs: primary ≥10 GiB free
VRAM and codec ≥5 GiB, plus 24 GiB available RAM. Auto chooses discovered devices;
advanced GPU selection chooses the primary. A 24-GiB user scope disables swap.
The worker and native runner both check admission; occupied resources queue.

The semantic model uses a 4096-token cache and at most 1024 generated semantic
frames per ≤220-character chunk. A 1000-character script is one ordinary Run,
with an absolute 30-minute deadline and complete-file publication. Every chunk
must terminate with EOS and yield finite nonsilent bounded PCM; the final file
must have exactly the sum of verified stem samples. These checks detect incomplete
inference, not arbitrary model mispronunciation or omitted words.

An actual isolated API → worker → CPU Whisper → owned native Fish test generated
4.41 seconds of whisper-directed speech and 33.20 seconds of happy/slow-directed
speech (three complete chunks). End-to-end times including reference preparation,
model verification/loading and publication were 113.64 and 185.41 seconds.
Subsequent offline ASR recognized both passages, including the long passage's
complete final sentence, with minor recognition deviations. Actual cancellation
during scoped model loading left no partial artifact, owned process or GPU lease.
That cancellation test also exercised reuse of a previously validated reference
transcript. Normal fake tests additionally cover lost dispatch acknowledgements,
inspect-before-retry recovery, private account/history/source access, changed
reference/transcript rejection, strict controls and RAM/GPU admission.

The reference transcript comes only from the existing successful transcription
Run and its intact owned transcript artifact. Cache reuse rechecks the exact WAV
snapshot; generated speech's requested text is not accepted as proof of spoken
words. Publication rechecks the same source and transcript. New uploads and
unavailable old caches use the ordinary local transcription prerequisite.

Private integrated evidence: `data/acceptance/fish-speech-integration-20261030/`.
Initial acoustic measurements alone did not establish strong audible differences
between all styles. The model/directions are optional; naturalness, voice fidelity
and consistent emotional control across scripts require listening acceptance.
Fish's noncommercial research-model license and **Built with Fish Audio**
attribution are shown in the UI; commercial use requires Fish's separate license.
This adapter does not close NR-06's listening acceptance or the full 0.1.0 scope.
