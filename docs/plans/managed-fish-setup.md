# Guided expressive voice setup (NR-06 / NR-14)

Status: the fixed Linux two-GPU candidate passed fresh-account installation,
Stop/Resume, compressed-reference transcription, complete generation and
Library playback, native restart/Task Stop and second-account privacy. Final
packaged/default-policy verification passed. PR #546 was reviewed, squash-merged
into develop and deployed, preserving the existing configured engines.
Preserve Chatterbox defaults and every existing runtime, voice reference and result.

## User journey

Models → Expressive voice inspects actual RAM and GPU capabilities, explains the
Fish model license and attribution, and offers one reviewed compatible profile.
The existing qualified BF16 profile requires two distinct GPUs (primary at least
10 GiB, codec at least 5 GiB), BF16 support and 24 GiB available host RAM. All
model parameters stay on GPUs. Show size, storage and requirements before the
administrator explicitly accepts installation. Incompatible hardware receives a
clear explanation rather than an offered install that cannot execute.

Use the existing Task → Run preparation lifecycle, private progress/receipts,
Stop/Resume, immutable object store, pinned interpreter and offline owned venv.
Only the built-in recipe may choose sources, wheels, models and destinations.
Ready is published after dependency checks, CPU imports and exact source/model
verification. Existing explicit native configuration retains priority.

The ready action opens Audio with Fish selected, without changing the user's
saved default. Upload or record a voice, enter the exact script, choose direction
and pace, then generate into ordinary private creative history and Library.
No manual transcription, model path or Python environment is part of this flow.

## Complete prerequisites

Freeze Fish Speech `0f8a12e8a651062fdee9c33a894bdccd3a8513f1` and the nine
S2 Pro files at `1de9996b6be38b745688de084d87a5633f714e4e`, already recorded in
`fish_contract.py`. Verify each complete object against publisher receipts.
Build a new independent environment; never repair the old venv in place.

Read-only inspection on 2026-10-31 verified 32,771 installed payloads in 133
selected inference distributions. It also found a genuine metadata conflict:
AudioTools 0.7.2 requires protobuf <3.20 while the old installation has 5.29.6.
A separate protobuf 3.19.6 candidate successfully imports Fish semantic and codec
modules without loading GPU weights. This is candidate evidence only: resolve
the full new closure, run pip check and qualify real complete inference before
freezing it as the managed recipe. No metadata conflict is waived.

The candidate now satisfies all 198 active inference requirements across the
133 selected distributions. Keep CPU ASR in a **separate owned venv**: the actual
qualified ONNX Runtime 1.31 requires protobuf >=4.25.8, incompatible with
AudioTools' <3.20 requirement. Do not combine these environments, edit dependency
metadata or downgrade the working ASR environment. One guided capability install
must prepare both closed environments and the reviewed Whisper model, reusing
the same verified interpreter object if suitable. ASR remains a separate CPU Run;
only verified PCM/text is passed to the Fish GPU process.

Fish needs a verified transcript of its voice reference. The guided profile must
also provide qualified offline CPU Whisper, its pinned model, PyAV and codec
dependencies, or reuse an already configured compatible transcription runtime.
The old Fish-only environment lacks PyAV; copying it alone cannot satisfy a
fresh installation.

Read-only source qualification now rechecks all nine Fish files (11,008,068,049
bytes) against the retained publisher receipt, including Git blob verification
for non-LFS files, and all 32 SDK source/config files against the qualified
source digest. The separate ASR selection has 23 distributions satisfying 31
active requirements. Public binary-wheel metadata resolves 130 Fish and all 23
ASR wheels; these are source/hash selections, not a downloaded/installed runtime.

The remaining three Fish dependencies require reviewed source builds:
ANTLR 4.9.3, ArgBind 0.3.9 and RandomName 0.2.1. The latter two fixed PyPI sdists
were inspected before execution and each wheel reproduced twice with the pinned
Python 3.12.14/setuptools 79.0.1/wheel 0.45.1, fixed build epoch and disabled
Python network access. The narrow native `fish_source_wheels` helper builds only
these exact source/version/hash combinations and rejects changed wheel outputs;
its actual three-wheel offline reproduction passes. It reuses the existing
qualified ANTLR build without changing Avatar or Effects preparation. This helper
is unregistered: no guided Fish profile is available from this work alone.

The complete candidate recipe now freezes 163 unique public inputs
(14,840,228,365 bytes), with explicit Fish/transcription environment groups,
13 model files, the pinned SDK and interpreter, and the three reproduced wheels.
The downloaded SDK archive matches all 32 qualified source/config files. The four
Whisper files additionally match the pinned publisher tree (LFS hashes or Git
blob hashes), not only the local manifest. This recipe is unregistered and
unqualified until independent offline assembly, typed lifecycle integration and
the fresh-user gates below pass.

Phone recordings may be M4A, MP3, WebM or another supported audio format. Extend
the existing bounded transcription decoder to optionally save its complete mono
16-kHz PCM as a WAV. Publish that derivative only after successful owned-process
completion, with exact source hash, transcription Run and artifact lineage.
Fish uses this verified WAV while retaining the original upload and transcript
binding. Preserve existing WAV/cached-transcript behavior. Recheck both original
and derivative before dispatch and final publication; reject changed, deleted,
foreign, truncated or overlong references. No external URL or arbitrary converter
command is introduced. Existing reports without normalization remain valid.

The phone-reference increment is implemented. A real AAC/M4A of the retained
synthetic neutral voice passed the existing owned native process, offline CPU
Whisper and exact canonical PCM sample comparison (66,131 samples). This tests
reference preparation, not new Fish inference, expression or fresh managed setup.
Private evidence: `data/acceptance/guided-fish-setup-20261031/`.

## Gates before availability

1. Hash-pinned public inputs, coherent dependency closure, independent offline
   assembly and CPU import/model probe inside an owned setup memory scope.
2. Normal fake tests for typed setup, invalid inputs, permissions, shared engine
   versus private receipt boundaries, lost acknowledgements and cleanup.
3. Fresh private account → setup Stop/Resume → compressed voice upload → offline
   transcription/canonical WAV → complete Fish output, without an old cache.
4. Same-process native restart recovery, Task Stop, no partial publication and
   released GPU/RAM reservations. Second account cannot read sources, transcripts,
   histories, logs or results.
5. Compiled desktop/phone journey, packaged native assets, regression checks and
   full PR review before qualification/default-policy activation and deployment.

Audible neutral/happy/sad/fearful/whisper/pace and Polish voice-fidelity acceptance
remain separate NR-06 gates. A direction selector, completed WAV or ASR transcript
alone does not prove expressive quality. This profile also does not close the
Linux/Windows/macOS consumer-installation or broader catalog requirements.

## Independent runtime qualification

The complete fixed recipe assembled successfully offline in an actual owned
4-GiB, zero-swap preparation scope. Both venvs passed pip check; the Fish semantic
and codec imports passed, and CPU Whisper loaded the pinned local model. Native
preparation uses the existing typed journal, immutable identity, absolute deadline,
Stop/adoption fences and private receipts; the installer remains qualification
controlled rather than enabled on this evidence alone.

The new managed-only ASR environment transcribed the synthetic AAC/M4A voice and
published 66,219 verified PCM samples without the original transcription runtime
or ambient application site-packages. A native-only two-GPU Fish invocation then
produced a complete 2.461-second, EOS-terminated result from that canonical voice.
These are real native results, not a browser/worker or audible-expression claim.

The first invocation failed because an existing external Ollama process acquired
about 5.2 GiB on each GPU during Fish's CPU loading interval. Its service was
left under its existing ownership. The wrapper now rechecks free VRAM immediately
before semantic weight transfer and codec loading, reporting resource contention
without publishing partial audio. The successful new attempt used a new Run after
the failed process and missing final artifact were confirmed; its first failure
and logs are retained. Rechecks reduce this loading race; external services do
not participate in AI Station's reservations and can still change GPU usage.

Normal setup/worker and UI contracts cover the new family, including source
verification, license acceptance, account revocation, recovery and Stop. Fresh
administrator UI setup/Stop/Resume, separate-worker generation, actual native
restart/Task Stop, account privacy, packaged default-policy checks and rollout
remain qualification gates. Operator cases SETUP-136–140 are untested until the
operator records results; automated evidence never pre-fills those answers.

## Fresh application qualification

An isolated fresh account installed the entire recipe from verified cached
public inputs through the compiled Models UI and a separate ordinary worker.
Stop and Resume retained the same Task with two attempts. The ready link opened
Audio with Fish selected; it does not change the saved default. The experiment
proves cached-input first setup, not a second network download of every weight.

The actual UI uploaded a synthetic neutral M4A reference and requested the exact
Polish text “Dzisiaj opowiem o naszej małej przygodzie.” with happy direction.
An ordinary CPU transcription Run produced the canonical WAV; the dependent
Fish Run used the same opaque environment identity and two GPUs. Its final
44,100-Hz WAV contains 108,544 samples (2.461 seconds), with EOS for the complete
text. Library decoding/seeking, saved creative history and desktop/390-px layouts
passed. This is functional evidence, not audible happy-direction acceptance.

A separate same-workspace follow-up retained its exact process PID/start time
through native Runner restart. Task-wide Stop confirmed that process gone,
published no partial artifact and released reservations while retaining the
first result. A second actual member sees shared engine readiness and its opaque
identity but receives 404 for the other account’s setup, Runs, workspace, original
recording, transcripts, canonical reference and generated audio. Installation is
admin-only. No production data or external service was changed by these probes.

Local regression evidence covers the full native suite and complete affected
backend families: 1,929 passed, two opt-in skips. All 1,064 baseline UI tests pass;
the final readiness wording and related Audio/setup families pass 16 cases.
Python lint/format, UI lint/types/format/build, Docker image build, three Compose
configurations and 26 offline QA-tool cases pass. The initially started unbounded
Python invocation was explicitly interrupted and is not counted as a pass.
The final policy-only native families pass 62 cases. Operator workbook answers
remain untested. Private evidence stays under the acceptance directory above.

The final candidate ran with the repository's default qualification policy,
without a private availability override. Its compiled setup and voice selection,
restored complete audio/history, desktop/phone layout and fake API/separate-worker
SSE passed after an idle private upgrade. The Docker image exactly matches 605
backend/frontend files, and the native wheel exactly matches all 195 approved
Python/recipe/shell assets. No completed GPU inference was repeated for packaging.

Production rollout preserved all 38 database tables, account credentials, managed
model observations, configured media engines, memory configuration/index and the
private access node. Final production desktop/phone controls and LAN health
passed without generating new content or capturing private Library screenshots.
The temporary verification device was revoked; only the owned QA services were
removed, with all model inputs, synthetic results and evidence retained.
