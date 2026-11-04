# Managed speech setup

This is the first multimodal bundle in NR-14, within the complete
[guided setup contract](guided-model-installation.md). It does not replace the
working configured Chatterbox or optional Fish adapters. The Linux x86-64 guided flow now prepares both the qualified runtime and its
companion files. Downloading weights alone remains a separate operation and
does not enable speech.

## Inspected source and files

The working helper uses `ChatterboxMultilingualTTS.from_pretrained(device=...,
t3_model="v3")` and explicit Polish generation/delivery controls. Its SDK reports
0.1.7 from immutable upstream commit
[`5de7a54`](https://github.com/resemble-ai/chatterbox/tree/5de7a54aa4e5e2baadb0182dde554908b48b85c2).
A version string alone is insufficient to reproduce that source. Dependency
metadata includes an unpinned Perth Git dependency; a managed runtime must lock
its complete inference dependency graph rather than execute that moving branch.

The published PyPI 0.1.7 wheel was also inspected: its multilingual loader lacks
the v3 selector used by the working Git source. The installed Perth is 1.1.0 at
[`ff1c8ac`](https://github.com/resemble-ai/Perth/tree/ff1c8ac55a976971245cdd53c18d6131ca00d993);
that version is not published on PyPI (whose inspected release is 1.0.1).
Do not replace either source merely because a package/version name looks
similar. Managed preparation must bind the inspected source revisions and
complete inference dependencies, with separately verified build inputs.

The matching public model snapshot is
[`ResembleAI/chatterbox@5bb1f6e`](https://huggingface.co/ResembleAI/chatterbox/tree/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18),
declared MIT by the publisher. The inspected loader selects `ve.pt`,
`t3_mtl23ls_v3.safetensors`, `s3gen.pt`,
`grapheme_mtl_merged_expanded_v1.json`, `conds.pt` and `Cangjie5_TC.json`:
3,208,951,924 bytes in total. Do not download the complete repository or silently
substitute its newer S3Gen files. Every selected object has its own SHA-256 and
length. Small Git objects were fetched at that exact revision and hashed, not
mistaken for Git SHA-1 values. Publisher metadata was checked on 2026-10-31.

## Delivery contract

1. Add a reviewed multi-file manifest and durable owner-bound bundle download
   using the existing immutable file primitive and Task/Run queue. Files share
   `models/store/<sha256>` without copying configured external caches. Aggregate
   progress identifies the current file, completed objects and verified bytes.
   Stop/restart retains good objects and partial bytes; explicit Resume uses the
   original snapshot. Register shared ModelFile rows and a private JSON receipt
   only after the entire bundle is verified and publication is serialized with
   Task Stop. No model Python or pickle is loaded during file preparation.
2. Freeze a reproducible managed inference environment for the inspected SDK,
   including the real Perth implementation/weights and tokenizer dependencies.
   Prefer checked binary wheels and an offline install in an app-owned venv
   using the bundled real Python. No system Python, external venv, driver or
   existing cache is changed. Native preparation must have immutable operation
   identity, owned process cancellation, deadline and inspection/recovery.
3. Add typed native bundle adoption and a repository-owned offline speech
   wrapper. Validate every source under the data root, assemble only the exact
   reviewed cache layout, retain watermarking, and prevent implicit downloads.
   Existing explicitly configured integrations keep their settings/defaults.
   Shared weights never make another user's reference recording accessible.
4. Finish the guided speech card: detected hardware, disk/runtime requirements,
   source/license consent, progress/history, Stop/Resume, real readiness and
   first speech using the user's own recording. Only actual qualified runtime
   readiness enables generation. Keep file-only preparation separate from
   installed/ready speech. Reuse normal audio Runs and creative history.
5. Qualify a real empty-data journey and dependency-free packaged interpreter,
   complete short/long Polish speech, Stop/recovery, account privacy and retained
   data. Expand to image/video/music/avatar companion recipes using the same
   bundle mechanism; all requested platforms remain in NR-13/14 scope.

## Boundaries and acceptance

Only catalog IDs and accepted manifest revisions enter the download API. No
caller-selected URL, file path, command, SDK or dependency version is accepted.
Administrator authority and effective model/network/workspace permissions are
checked throughout execution and before publication. Worker ID plus claim
timestamp fence progress, deferral, errors and lock release. A stale worker
cannot publish, cancel or fail its replacement. Failed/incomplete preparations
cannot create model definitions or claim inference readiness.

Normal tests use tiny fake objects, temporary databases and fake hardware.
Coverage includes multi-file interruption, unchanged frozen Resume, cached-object
reuse, aggregate progress, invalid sources/paths, hash failure, Stop/claim races,
resource deferral and A/B/admin API/artifact ownership. Real downloads and speech
qualification are explicit opt-ins and reported separately. No runtime adapter
is operational merely because the manifest or download receipt exists.

## Qualified file-preparation increment

`GET /api/setup/bundles/catalog` exposes reviewed file manifests and storage;
`/api/setup/bundles/downloads` provides administrator submissions and private
history, detail, Stop and explicit Resume. Request bodies accept a catalog ID,
manifest fingerprint, idempotency UUID and license confirmation. HTTP requests
only enqueue. The worker reuses the existing verified file primitive, RAM
admission, task/claim fences, shared ModelFile registry and private artifacts.
It creates no model definition and always reports `runtime_prepared=false` and
`ready_to_try=false`. The guided speech runtime described below is a separate
explicit action, reusing those verified objects.

An opt-in real-object check in isolated storage verified all six actual files,
stopped during full-weight hashing, resumed against the original manifest and
published the complete private receipt through the real account/API/worker/SSE
path. Four weight objects were copied from the existing cache for isolation;
the two tokenizer JSON objects were actually downloaded from the pinned public
source. This is not a full new weight-network-transfer or speech-inference
claim. Existing caches, runtimes and production records were unchanged. Evidence
is private under `data/acceptance/guided-media-model-setup-20261031/`.

## Qualified managed speech flow

Models → Set up a local model offers **Set up speech**. The optional card
opens automatically from Audio's setup link. Hardware, required storage, exact
sources and licenses are shown before consent. A new installation needs Linux
x86-64, glibc 2.28+, the packaged CPython 3.12 Runner, user-level memory scopes
and an NVIDIA GPU with at least 6 GiB VRAM. This is a measured speech profile,
not a claim that every platform or other media runtime is ready.

One administrator submission creates an ordinary private runtime-preparation
Task/Run. The worker downloads or rehashes the frozen inputs, records aggregate
file progress and then dispatches the fixed native operation. Setup history and
progress survive changing tabs or reopening the application. Native assembly is
reported by its real phase rather than a fabricated percentage. Stop retains
verified objects; explicit Resume creates a new attempt against the original
manifest. Successful preparation opens Audio, where a reference WAV and a script
create a normal private speech Run and Library artifact. Preparation alone never
claims that inference has run.

The fixed Linux x86-64 / CPython 3.12 / CUDA 12.6 recipe binds 126 binary wheels,
the two immutable SDK archives, six model objects, segmentation archive and
standalone Python: **136 objects, 6,489,550,701 bytes** before installation. Each
input has a public HTTPS source, exact length and SHA-256. Eight GiB of additional
assembly space is reserved in the estimate. Components retain their separate
licenses; the MIT model license does not license the bundled NVIDIA components.

All inputs live in the immutable app-owned store and are hashed before any
package executes. Preparation extracts its own pinned CPython and stdlib, then
creates a private venv, so removing an old application version cannot remove its
interpreter. Source SDKs build offline with pinned setuptools/wheel/uv_build,
without online dependency resolution, Git or a system compiler. `pip check` and
the offline probe must succeed before readiness is written. Incomplete operation
directories are retained and never reused as a completed environment.

SDK and segmenter extraction rejects traversal, links, special files and oversized
contents. Standalone Python permits its legitimate in-tree links through the
standard safe extraction filter and verifies their final targets remain inside
its owned Python tree. Model/wheel aliases point only to verified immutable
objects; large weights are not copied. The probe verifies the v3 selector,
Chinese mapping/snapshot layout, offline segmenter, owned base Python and actual
Perth watermark checkpoint. The fixed speech CLI blocks Python network
connections and loads `from_local`; this does not claim to sandbox arbitrary
third-party code or provide an internet tool.

## Native, worker and account boundaries

`/v1/setup/speech` exposes typed catalog, prepare, inspect, cancel and adopt
operations over the existing private Runner socket. Only the built-in profile,
manifest and absolute deadline are accepted. A private immutable journal and the
existing ProcessManager own the four-GiB/zero-swap preparation group. Repeated or
lost-acknowledgement dispatches inspect the same operation. Stop is durable before
dispatch; Stop/adoption serialize against the same native lock. Missing process
or completion evidence requires inspection and never silently repeats setup.

The control plane reuses `/api/setup/runtimes` with the speech profile and the
existing runtime supervisor. Live administrator authority, effective permissions,
Task Stop, worker identity and claim timestamp fence progress and publication.
Revocation uses trusted worker-only cancellation of the exact existing action,
without impersonating the disabled account. Shared ModelFile rows and private
JSON receipts publish only after all files, native completion and activation
receipts verify. Account A cannot read B's history, logs or receipts; shared model
files do not expose voice references or generated speech.

Existing explicit Chatterbox settings always retain priority, including partial
configurations that need repair. Managed setup cannot silently replace them.
Otherwise Audio resolves the activated, exact prepared recipe. Normal speech
Runs freeze that manifest, reserve load RAM and one eligible GPU, and recheck the
selected runtime before launch. The fixed inference child verifies an eleven-GiB,
zero-swap kernel scope and uses the existing 220-character chunk policy with the
model loaded once. Invalid, partial or token-limit-length parts never publish a
final WAV. All parts publish together without overwriting an existing result.

## Qualification and remaining release scope

Normal temporary-database/fake-executor cases cover the preparation lifecycle,
manifest/path/hash rejection, cancellation before/during dispatch, immutable
lost acknowledgements, Stop/adopt serialization, lease-epoch races, account
revocation/isolation, registry publication, configured-runtime preservation and
managed Audio dispatch. Frontend cases cover consent, setup, Stop/Resume,
history restoration and unavailable hardware. No normal test downloads models
or launches real inference.

Explicit real qualification is retained privately under
`data/acceptance/managed-speech-runtime-20261031/`:

- The complete actual account/API/container worker/private Runner/UI journey
  prepared all 136 inputs, installed the SDK with its own Python and generated a
  first recording through an ordinary Audio Run on CUDA. Desktop and phone
  layouts, navigation restoration, private receipt and SSE passed. That journey
  reused isolated cached inputs and rehashed every object; it did not download
  another 6.49 GB from the network.
- A separate cold-source check used the actual application downloader for both
  SDK archives, Python and segmentation archives, plus a real wheel from each
  distinct wheel host. Exact lengths/hashes passed. This proves those selected
  public transfers, not a new network transfer of every full weight.
- Short and longer Polish CUDA recordings completed; the longer current sample
  was 28.48 seconds. Earlier measured peak allocated GPU memory was approximately
  3.5–3.6 GiB. Actual Stop during generation ended only the owned group and
  published no partial final WAV. Offline Whisper checks retain recognition
  errors and do not replace human listening/style acceptance.
- A native lifecycle check verified setup, repeated dispatch with the same PID,
  inspection and activation under its actual four-GiB/zero-swap scope. The full
  native test suite passed 1,314 cases (two optional skips).

The separate file-only qualification is retained under
`data/acceptance/guided-media-model-setup-20261031/`. Production rollout remains a
separate reviewed operation. Image/video/music/avatar recipes, clean consumer OS
installation, Windows/macOS qualification and the remaining NR-01–NR-14 release
requirements remain in scope; this speech delivery does not complete them.
