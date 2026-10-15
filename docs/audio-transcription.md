# Offline audio transcription

Audio → Transcribe recording uses Whisper in a separate optional native Python
runtime. Upload a 16-bit PCM WAV recording (mono/stereo, 8–96 kHz, 0.1–300 seconds,
maximum 20 MiB), or select one from Library. Select its language or let Whisper
detect it. Send creates an ordinary Task and CPU-only host Run. The result has
timestamped speech, copy, TXT/SRT/JSON downloads, original-recording provenance,
Run inspection and a restorable `/audio?mode=transcribe&run=<uuid>` URL.

The central Chat/Work supports **Transcribe recording** and deterministic requests
such as “Przepisz to nagranie” with an attached recording. It publishes the same
native child Run under the conversation Task and renders its transcript inline.
It does not load a conversational model, send audio to an external provider or
execute instructions heard in a recording. Transcription accuracy depends on the
installed model and recording; names and important facts need checking.

## Runtime setup

The feature stays unavailable until both settings are configured:

```
AI_STATION_TRANSCRIPTION_PYTHON=/absolute/path/to/whisper-venv/bin/python
AI_STATION_TRANSCRIPTION_MODEL_DIR=/absolute/path/to/offline-ctranslate2-model
```

Create a dedicated Python 3.12 virtual environment and install
`scripts/transcription-requirements.txt`. This does not alter an existing AI
runtime. Supply an already downloaded CTranslate2 Whisper directory containing
`model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt` and a reviewed
`ai-station-model.json` manifest:

```json
{"version":1,"model":"model identifier","revision":"immutable revision","files":{
  "model.bin":{"size":123,"sha256":"actual 64-character SHA-256"},
  "config.json":{"size":123,"sha256":"actual SHA-256"},
  "tokenizer.json":{"size":123,"sha256":"actual SHA-256"},
  "vocabulary.txt":{"size":123,"sha256":"actual SHA-256"}
}}
```

If `preprocessor_config.json` is present, include its size and SHA-256 too; it
changes feature extraction and is verified alongside the required model files.
Use actual sizes and hashes verified against the selected model release. No
weights are downloaded by startup, the API or a Run. The deployment's tested
small model is `Systran/faster-whisper-tiny` at
`d90ca5fe260221311c53c58e660288d3deb8d356` (MIT, ~75.5 MB model.bin). This is an
initial fast CPU profile, not a claim of perfect speech recognition. Larger
reviewed offline Whisper models can be configured explicitly. Restart only AI
Station's Host Runner after changing its runtime/model configuration.

## Execution and security

The Runner exposes typed transcription capabilities, dispatch and verified-report
operations. Requests contain only Run UUID, immutable app-owned source descriptor,
language, model-manifest fingerprint and two permissions (`filesystem_read`,
`workspace_write`). No shell, arbitrary model path, URL, prompt or GPU identifier
is accepted. Canonical relative paths, source hashes and all model file hashes
are checked at submission/dispatch and in the independent runtime.

Only complete bounded PCM WAV data is accepted. Audio is decoded with the Python
WAV reader into a bounded array; Whisper receives samples, never a caller's URL
or a decoder playlist. Automatic downloads are disabled and the model is loaded
from its checked local directory with `local_files_only=True`. CPU int8, two
threads, one model worker and a ten-minute hard process deadline bound execution.
The bundled offline VAD reduces silent-region hallucinations; detected timestamps
are clipped to actual recording duration before report validation.

An immutable private request journal makes repeat dispatch inspect the same owned
process, never launch another one. Cancellation signals only its managed process
group. Reports require confirmed exit code zero, matching Run/source/model, finite
ordered timestamps and bounded content before any artifacts appear. Canceled,
failed or uncertain processes cannot publish a transcript. Worker recovery uses
the shared conservative inspection policy; it does not replay an uncertain Run.
The original remains in Library. The existing 60-second speech-reference upload
contract is unchanged.

## Verification

Normal tests use fake runtimes and temporary databases. They exercise typed API
validation, permission rejection, model/audio hash changes, symlink escape,
idempotent dispatch, owned cancellation, output bounds, failure/uncertain exits,
worker artifacts, separate voice-upload limits and Chat/Work routing without AI.
Frontend tests cover submission, Stop, saved-result URLs and unavailable setup.
Real inference is opt-in and must be reported separately from these checks.

Local acceptance on 2026-10-15: actual 14.27-second Polish recording through the
API, worker and owned CPU process produced timestamped speech and all three
source-linked downloadable artifacts. Desktop (1440 px) and mobile (390 px)
browser checks displayed that actual result without page errors or overflow.
Normal checks: full Python suite 1212 passed/5 explicitly opted-out integrations;
final focused boundary/recovery checks passed separately after review fixes.
Full frontend suite: 428 passed; final focused UI checks, lint, TypeScript,
format, production build, Compose validation and Docker image build also passed.
This is not a five-minute-recording or other-model hardware acceptance claim.
