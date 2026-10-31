# Guided local music setup

NR-14 follows the delivered speech/image/CPU-memory setup. Preserve the existing
ACE-Step adapter and explicit Python/source/model configuration, including partial
configuration that needs repair. Do not install into or modify that environment.

The current approved `ace-step-1.5-turbo-no-lm` preset binds the existing
`music_protocol.py` code/model revisions and its canonical sixteen-file manifest.
Public source audit confirms the [pinned model repository](https://huggingface.co/ACE-Step/Ace-Step1.5/tree/19671f406d603126926c1b7e2adc169acbcade22)
and [pinned MIT SDK](https://github.com/ace-step/ACE-Step-1.5/blob/ca1e85fe9430179831e6bc6be790c332190a3866/LICENSE).
The existing complete environment is observed, not upgraded: its installed
versions have 74 public wheel sources (4,288,575,477 bytes). The model files total
6,336,680,772 bytes. Python, CUDA and embedded model components retain their own
licenses; review the component list before explicit installation. An audit is
not runtime readiness or inference qualification.

## Delivery contract

- Freeze a built-in recipe with standalone Python, the source archive, exact
  wheel URLs/hashes/lengths and all model companions. Reuse the existing reviewed
  downloader, shared immutable store and private runtime-preparation Tasks/Runs.
  No arbitrary package, source URL, image, command or destination is accepted.
- Reuse the existing owned preparation/process journal, deadlines, resource scope,
  Stop-before-dispatch, lost-acknowledgement reattachment, claim/revocation fences
  and adoption gates. Extract common lifecycle policy where needed for this
  second offline environment; preserve speech contracts and source fingerprints.
- Assemble a separate offline environment with its own Python/stdlib, exact wheels
  and audited source. Never run dependency resolution or upstream auto-download
  during installation/inference. Verify SDK Python bytes against the existing
  approved music source hash before imports. Unfinished assembly cannot activate.
- Keep model objects single-link and immutable. A managed model tree may use only
  closed-world links to the recipe's exact store objects, checked before use;
  existing external paths retain strict symlink rejection. A per-Run checkpoint
  view uses the approved SDK model code without changing installed weights.
- Ordinary music Runs freeze the managed recipe/environment observation, preserve
  caption/lyrics/seed/duration, reserve resources and publish the same WAV artifacts,
  creative history and lineage. Old snapshots and explicit configured runtimes
  keep their existing behavior. No second music execution architecture.
- The current adapter explicitly offloads portions to CPU. Report this accurately
  with its RAM reservation; do not claim GPU-only fit. A managed inference child
  needs a tested zero-swap scope/deadline and the existing owned process-group
  cancellation/recovery. Do not change the working external preset to pass tests.
- Add a Models music card and Audio missing-runtime entry using existing setup
  styling: actual hardware/storage, licenses, saved measured progress, Stop/retry,
  and a first instrumental/song in the ordinary Music workspace. No green Ready
  from file downloads or imports alone.

## Qualification and rollout

Normal tests use tiny fake objects/processes and temporary databases. Cover source
hashes, archive/link boundaries, offline assembly, frozen/repeated preparation,
Stop/recovery/adoption, stale claims/revoked accounts, shared model/private history,
source changes between admission/dispatch, artifact verification and scoped cleanup.
Real opt-in qualification must use a fresh account and compiled desktop/phone,
ordinary API/separate worker/native setup, actual model inference and complete
WAV playback/metadata, navigation/restart, Stop/recovery and account denial.
Reuse matching existing model bytes for isolated qualification without modifying
originals or downloading them again. Preserve the current deployment and data
until the complete profile has been reviewed and qualified.

## Qualified managed music flow — 2026-10-31

The fixed Linux x86-64 / glibc 2.28+ profile is qualified on this workstation.
The card requires a compatible NVIDIA GPU with at least 12 GiB VRAM, at least
24 GiB system RAM, the user resource manager and sufficient free storage. The
92 pinned inputs total 10,667,839,025 bytes. Complete matching immutable files
are verified and reused. Offline assembly reserves 4 GiB RAM; inference uses
12 GiB up to one minute and 18 GiB for longer tracks, with zero swap. CPU offload
is intentional; this is not a GPU-only claim. The ordinary adapter retains its
10–600-second duration limits and supplied-lyrics/instrumental choices.

Real opt-in qualification used a separate data root, first administrator, Docker
API and separate worker, private Unix Runner and the compiled application:

- Reviewed sources/licenses, started setup, stopped during actual dependency
  installation and resumed the same Task as attempt 2. Verified cached files
  were retained; readiness followed complete offline preparation and adoption.
- Created a 30-second instrumental through ordinary Music submission, reloaded
  the saved Run and opened its complete WAV in Library. Browser decoding,
  duration and seeking passed. Desktop and 390-pixel phone setup had no horizontal
  overflow; no JavaScript errors were observed.
- Restarted only the private Runner during actual managed music generation.
  Inspection retained the same owned PID/start identity. API Stop confirmed the
  process gone, released reservations and published no partial artifact.
- A second real member account could observe shared engine readiness but could
  neither install nor access the administrator's setup, Runs or artifact/file.
  Explicit/partial external configuration remains authoritative in regression tests.
- Separate native-boundary tests generated complete 10-second and 600-second
  48-kHz stereo WAVs. The latter took 73.44 seconds on one RTX 3060 12 GiB under
  its actual 18-GiB zero-swap scope. This is a native runtime observation, not an
  application latency benchmark or perceptual music-quality assessment.

The full frontend regression passed 1,030 tests; the final native suite passed
1,456 with two opt-in integrations skipped. All 375 affected backend cases in
24 complete families passed, covering lifecycle, download, model boundaries,
accounts, recovery and revocation. Ruff/format, frontend lint/typecheck/build,
Compose validation and 26 QA-export checks passed. The final image's 589 backend
and frontend files and the native wheel's 165 source/recipe files matched the
reviewed tree. Final compiled desktop/phone, history/audio restoration and a
separate fake API/worker/SSE run passed with the default native policy.
Packaged source/build checks and production rollout are recorded separately;
qualification alone does not mean a candidate has been deployed.
Private evidence: `data/acceptance/guided-music-setup-20261031/` (input/environment,
native-music, app and recovery/privacy proofs). Operator QA cases SETUP-117–120
remain untested answers until the owner executes them.

This plan keeps all remaining video/avatar/effects/expressive-voice setup, broader
catalog/hardware support, actual consumer Linux/Windows/macOS install/update/
uninstall, NR-06/07 quality, naming and final operator workbook in scope. It does
not mark the full release complete.
