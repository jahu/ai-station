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
script. Every complete chunk receives the selected direction; speaking pace uses
pitch-preserving processing of that complete PCM: Slower is 0.8× speed and Faster
is 1.25×. Natural leaves the decoded PCM unchanged. This uses librosa already in
the fixed offline Fish environment, inside the same owned process and resource
budget, without another download. The report records the method, rate and original
and final sample counts; complete EOS is still required before processing. Creative
versions restore them. Chatterbox remains the default and its legacy requests
retain their original serialized identities.

The real seven-direction/pace API/worker/GPU matrix found that the old `[fast]`
tag produced 4.92 seconds against 4.78 seconds for Natural on the same Polish
script/seed; `[slowly]` produced 6.50 seconds. Tags alone therefore did not provide
a reliable pace control. Emotions remain model-generated; the pace correction
changes duration rather than asking the model to reinterpret the words. The
seven outputs passed EOS, decoding and approximate offline ASR observations;
those observations are not human listening acceptance.

The correction at `43201f3` passed an actual private-account API → separate
worker → Unix Runner → dual-GPU comparison, with no fake executor. The same
Polish text, direction and seed yielded 210,944 model samples in all three Runs:

| Speaking pace | Complete output | Speed |
| --- | --- | --- |
| Natural | 4.7833 seconds | 1.0×, unchanged PCM |
| Slower | 5.9791 seconds | 0.8× |
| Faster | 3.8266 seconds | 1.25× |

All three ordinary private artifacts passed EOS, canonical WAV and recorded
sample-count checks. GPU/RAM reservations were released and the temporary test
services stopped. The idle AI Station-owned LLM was restored through ordinary
audited Stop/load Runs to its saved model/image, GPU and 131,072-token Q8 cache
preset; unrelated services were untouched. A separate bounded CPU check retained
the exact 220-Hz tone peak at both rates and processed real generated speech.
Evidence is private under `data/acceptance/fish-reliable-pace-20261103/`.
Perceptual fidelity remains an explicit operator gate, covered by `VOICE-005`;
these measurements do not establish audible quality for every voice or language.

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

## Phone voice references and guided setup

Fish accepts the existing supported recording formats, including M4A, MP3 and
WebM, through the ordinary private upload and transcription pipeline. A compressed
reference requests a canonical mono 16-kHz PCM WAV from the exact decoded ASR
samples. Only successful complete transcription publishes that derivative;
original recording and transcript provenance remain bound and rechecked before
GPU dispatch and speech publication. The reference still has a 60-second limit,
validated after decoding, and no partial or overlong source is sent to Fish.
Existing WAV references and their verified transcript caches retain their path.
Chatterbox continues to require WAV. A Runner lacking canonical-reference support
rejects compressed Fish submissions before queueing rather than failing mid-job.

The [guided installation plan](managed-fish-setup.md) includes CPU transcription
and codec prerequisites. Its dependency candidate is separate from the historical
configured runtime above; guided readiness and real fresh-install qualification
remain unfinished.

## Voice-source conditioning study and explicit model voice (2026-11-03)

Private GPU-only comparisons used the pinned configured S2 Pro source/weights,
existing synthetic voice reference, seed 42 and identical Polish words. Eight
complete-EOS samples compared the current whisper tag, the publisher's canonical
`[whisper]`, explicit source-speaker binding, free-form quiet whisper, natural,
happy, sad and afraid. The current whisper reproduced the retained baseline
byte-for-byte. Canonical tags/binding alone do not establish an expression fix:
voiced fractions remained about 0.81–0.88 with similar median pitch.

A separate controlled four-sample comparison checked English with that same
reference and Polish without a reference. Referenced English natural/whisper
remained about 0.79/0.82 voiced, with complete approximate ASR transcripts.
Without the reference, Polish natural/whisper changed from about 0.72 to 0.08
voiced and spectral flatness from 0.0034 to 0.0889. This supports neutral-reference
conditioning as a material factor for this voice/seed; it is not general proof
of every voice, audible quality, identity fidelity or emotion. Unvoiced-frame
pitch estimates must not be interpreted as the whispered voice's pitch. No
operator process was stopped, external model changed or production data written.
Evidence remains private under `data/acceptance/fish-prosody-20261103/` and
`data/acceptance/fish-prosody-reference-20261103/`; listening remains open.

The candidate adds an explicit **Generate a voice / Use a recording** choice
for Fish in Audio and reviewed speech agents. It never silently drops a supplied
voice reference to improve delivery. Existing requests/history retain reference
mode and their identity; Chatterbox keeps its WAV contract. Model voice is an
explicit Fish-only request, rejects mixed reference inputs, omits the ASR
prerequisite and has no voice-recording lineage. Agent text-preparation provenance
remains in the ordinary artifact lineage. The worker/native receipt freeze
that choice; privacy, typed permissions, dual-GPU/RAM admission, EOS/chunk checks,
Stop and recovery retain their existing contracts. Creative drafts/follow-ups and
agent review must preserve the selection. API/schema, native dispatch/cancellation,
private lineage and actual UI/worker/GPU checks precede availability. The
qualification below covers the normal worker/hardware path; deployment and
listening acceptance remain separate.

### Integrated generated-voice qualification

The exact candidate at `b194d9a` passed a fresh private-account API → separate
worker → real native Unix Runner → dual-GPU Fish execution. It produced an
EOS-complete, decoded **5.53-second Polish whisper** without a reference, ASR Run
or fabricated executor. The result was published through the ordinary private
artifact endpoint with `voice_source=model`.

A second real owned Fish process survived abrupt loss of only the private
worker group. Its replacement inspected the same native PID without redispatch;
ordinary API Stop then canceled that process. No partial audio was published and
the private GPU/RAM leases were released. The Runner and both private workers
were stopped afterward. The workstation's idle AI Station-managed LLM was
temporarily unloaded through an audited, owner-scoped Stop Run and restored
through an ordinary load Run with the same model, GPU assignment, context,
cache and image. External runtimes were unchanged.

Evidence remains private under `data/acceptance/fish-model-voice-api-20261103/`.
This verifies execution, cancellation and recovery; it does not establish human
listening acceptance of every emotion, script or cloned speaker.


### Explicit Chatterbox language (2026-11-07)

The public showcase needs real English recordings rather than relabeled Polish
outputs. Audio and the shared speech request accept English explicitly. The
worker freezes a statically advertised CLI source hash; native dispatch rejects
an unsupported or changed contract. Every long-text child inherits the selected
language. Existing requests and independent Polish adapters keep their behavior.
The app-owned configured v3 launcher reuses an existing cache and Python offline;
it does not modify external `clone_pl.py` or download weights. Managed multilingual
speech uses its existing prepared SDK and cache. Fish remains automatic by text.

Fake-process tests cover direct/chunked English, unsupported-language rejection,
source replacement, ownership-safe cancellation, legacy request identity and
Fish compatibility. SDK fakes exercise real configured-launcher argument routing,
offline enforcement and non-overwriting publication. Real English inference is a
separate opt-in qualification, not implied by these tests.
