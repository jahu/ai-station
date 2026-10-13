# Local speech

The Audio workspace queues `audio.speech` Tasks and `chatterbox` Runs. It wraps an administrator-configured installation of `clone_pl.py`, using its inspected `--ref`, `--text` and `--out` arguments. The current adapter produces Polish speech; it does not pretend to support music or other languages.

Uploads accept bounded, decoded PCM WAV references (mono/stereo, 8–96 kHz, 0.1–60 seconds, at most 20 MiB). Inputs and outputs are ordinary audio Artifacts with source lineage; Library, Audio results and the assistant inspect those sources and any derived video from the same graph. Text is bounded to 1000 characters. The Library can play and reuse a WAV. A finished Audio result offers the same Use as voice reference action in place; it stages that artifact as the next source, keeps the previous Run in the URL for the still-visible output, and does not queue a Run. Use as speech stages that WAV into Avatars without another Run. Text, parameters, GPU, logs and result remain inspectable in Runs. The GPU target radios reuse the shared list keyboard with unique Target GPU names; Space or Enter selects a row and does not queue a speech Run. There is no inspectable GPU-target Run.

Configure `AI_STATION_CHATTERBOX_PYTHON`, `AI_STATION_CHATTERBOX_SCRIPT` and `AI_STATION_CHATTERBOX_CACHE` on the native Runner. The cache is an existing Hugging Face home, not a download destination populated by AI Station. Offline environment flags prohibit automatic model downloads. GPU visibility is restricted to the selected discovered device. Original scripts and models are not rewritten.

Photo and speech adapters share HostMediaExecutor for reservations, idle managed-model eviction, dispatch journaling, polling, cancellation and artifact registration. The existing photo argv builder and behavior are retained. The Runner validates UUID ownership, effective read/write permissions, canonical artifact paths, WAV bounds and actual GPU presence before starting an owned process group. Output paths are derived from the Run UUID. Canceled or interrupted work is not blindly retried; uncertain dispatch retains ownership/resource reservations for existing recovery inspection.

Real installation probe (2026-09-28): the existing Chatterbox environment and offline cache generated a 1.68-second, 24 kHz WAV from a local reference and short Polish text. This standalone probe does not yet establish application end-to-end acceptance.

The platform assistant accepts a WAV voice reference with the explicit Speech action and returns the generated audio inline. Ordinary text-only conversation rejects media actions. Mixing voice references with images/documents is rejected; transcription is not implied. Deterministic actions bypass planner-model loading.

Real application acceptance: isolated API upload → queued Run `93a9893f-b8ca-4880-ba67-d8dfc2cabcdb` → native Chatterbox → 3.76-second mono 24 kHz WAV artifact → inline file response and released GPU reservation. The original reference and installed environment were unchanged.

Real browser acceptance (2026-09-28): Audio upload and generation, decoded WAV playback in Library, and an assistant speech child Run with inline playback all passed without browser JavaScript errors. These checks establish playable output, not a subjective pronunciation assessment.

The Audio workspace keeps composition and output side by side. Voice references support drag/drop, file selection and Library reuse. The inline Library list is one keyboard sequence (arrows, Home, End, Enter attaches) with unique Choose names. Generation shows its live state, stop action and playable result in place; the Run inspector remains available for logs. The result's Run ID is preserved in the URL for reopening after navigation or refresh. GPU selection lives in Advanced settings.

Portraits can now use a voice reference and typed Polish speech through a sequential Chatterbox → EchoMimic workflow, retaining both outputs and following the active stage after refresh. See [speaking avatars](speaking-avatars.md).
