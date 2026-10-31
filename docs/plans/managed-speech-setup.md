# Managed speech setup

This is the first multimodal bundle in NR-14, within the complete
[guided setup contract](guided-model-installation.md). It does not replace the
working configured Chatterbox or optional Fish adapters. Fresh installations
must eventually obtain both a qualified runtime and all companion files through
the guided flow; downloading weights alone does not complete that requirement.

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

## Implementation sequence

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
`ready_to_try=false`. The normal guided conversation-model UI is unchanged;
the speech wizard and qualified runtime remain required implementation work.

An opt-in real-object check in isolated storage verified all six actual files,
stopped during full-weight hashing, resumed against the original manifest and
published the complete private receipt through the real account/API/worker/SSE
path. Four weight objects were copied from the existing cache for isolation;
the two tokenizer JSON objects were actually downloaded from the pinned public
source. This is not a full new weight-network-transfer or speech-inference
claim. Existing caches, runtimes and production records were unchanged. Evidence
is private under `data/acceptance/guided-media-model-setup-20261031/`.

## Managed environment implementation

The native package now contains a fixed Linux x86-64 / CPython 3.12 / CUDA 12.6
recipe, an offline assembler, a preparation probe and an internal Polish speech
CLI. These remain internal helpers, with no HTTP route, executor registration,
automatic activation or replacement of configured external Chatterbox settings.
Account-bound download/dispatch, cancellation/recovery and the guided speech
card must be completed before this becomes a selectable managed runtime.

The recipe binds 126 exact binary wheels, the two immutable SDK archives, the
six model objects and the upstream segmentation archive: 135 objects totaling
6,455,407,333 bytes before installation. Every object has a public HTTPS source,
exact byte length and SHA-256. Dependencies retain their separate licenses;
the MIT speech model license is not a license for bundled NVIDIA components.
Source SDKs are built offline with pinned setuptools/wheel/uv_build and no
dependency resolution or Git invocation. No system compiler is needed for these
two Python packages. The complete installed graph is checked with `pip check`.

The assembler requires all inputs in the immutable app-owned store and hashes
them before executing any package. It uses the native packaged interpreter to
create a separate venv, preserves incomplete operation directories, never
overwrites another attempt and writes readiness only after its offline probe
passes. Its subprocesses inherit the dispatcher's owned process group/deadline;
this is not an independent process supervisor or a background shell service.
The future native dispatch must supply that supervisor and claim/account fences.

Model and wheel aliases stay inside the new environment and point only to its
verified immutable objects; large weights are not duplicated or hard-linked.
SDK/segmenter archives reject traversal, links, special files and oversized
contents. The Chinese mapping has the precise HF snapshot/ref layout required
by the inspected tokenizer. The separate `spacy_ontonotes.zip` is verified and
extracted before inference, so its default initializer does not download it.
The probe disables Python network connections and checks the v3 selector,
complete mapping/segmenter and the real packaged Perth watermark checkpoint.
The speech CLI also blocks Python network access and loads only `from_local`.
This guard supplements the future native execution boundary; it does not claim
to sandbox arbitrary third-party code or expose a browser/network tool.

Normal boundary tests require no models, installer execution, GPU or network.
Real preparation/speech qualification is opt-in and private under
`data/acceptance/managed-speech-runtime-20261031/`. A successful environment probe
proves import/tokenizer prerequisites, not successful speech inference, clean-OS
installation or completion of NR-13/14 on any platform.

The actual isolated assembler passed with the packaged CPython 3.12 interpreter,
all 135 real inputs and no online install resolution. Its built native wheel was
also inspected to ensure the complete recipe and helper sources are included.
Real Polish CUDA samples produced 10.28-second and 27.4-second PCM results; the
longer result used two existing 220-character chunks with the model loaded once.
Observed allocated GPU peaks were about 3.5–3.6 GiB. The actual child verified an
11-GiB RAM, zero-swap kernel scope. Stop during actual model execution ended the
owned group and published no partial final WAV. This is internal model/runtime
qualification, not an account/API/wizard or clean-OS installation claim.

The first unchunked long experiment continued with unrelated speech until the
model token limit. It is superseded: the helper now uses the established text
chunk policy, rejects invalid/token-limit-length parts and publishes the whole
PCM result without overwriting an existing file. Offline Whisper-tiny checks
provide intelligibility evidence, with recognition errors still visible in the
private transcript; they do not replace listening/style acceptance. The normal
external Chatterbox adapter and its existing chunk wrapper were unchanged.
