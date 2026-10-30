# Guided installation and hardware-aware model setup

This implements NR-13/14 of the [0.1.0 release contract](next-release-0.1.md).
All three requested platforms and all creative capability families remain in
scope. Current production still uses the documented Linux prerequisites. The current candidate adds a Linux guided conversation-model workflow, not
the complete cross-platform launcher or a complete multimodal installation.
Production release status is separate from the evidence below.

## User journey

1. The desktop launcher checks prerequisites and starts the existing Docker
   control plane and native user Runner. First launch creates the administrator
   through the existing local bootstrap proof; returning users retain accounts,
   settings, Library and conversations.
2. **Set up your station** reads actual RAM, available storage, devices and
   runtime capabilities. Ready existing integrations appear first and require no
   replacement download. The user chooses conversation, images, video, speech,
   music, avatars and memory. Existing personal defaults remain authoritative.
3. Each recommendation shows the model/quantization, expected download and disk
   size, license/source, supported runtime/platform and an estimated memory fit
   with headroom. Busy resources are distinct from insufficient capacity.
   Context/GPU settings are chosen from the existing fitted llama.cpp admission;
   the installed GGUF header and actual load remain authoritative.
4. The user confirms the chosen downloads and license information. Ordinary
   Tasks/Runs show actual byte progress, Pause/Stop and explicit Resume. The
   wizard can be closed and reopened; installation state is durable.
5. Verified weights are adopted by a typed native operation, required runtimes
   are prepared from pinned recipes, readiness is checked and a short real first
   result is offered. Only a successful result makes a capability ready. The
   advanced catalog can select alternative qualified quantizations/profiles.

The launcher never silently installs drivers, replaces CUDA, alters existing
models/runtimes or exposes public networking. Windows uses a qualified WSL2 user
Runner/Docker route; macOS needs actual native CPU/Metal-compatible adapters.
CUDA-only media must remain clearly scoped until another backend is qualified.
Clean-machine installation, first inference, update and data-preserving uninstall
must be exercised on every advertised platform.

## Catalog and file identities

Keep installed-model discovery (`model_catalog.py` and the existing registries)
separate from the reviewed downloadable catalog (`setup_models.py`). HTTP clients
select a catalog ID and accepted manifest/license revision; callers and models
cannot supply commands, download URLs, destination paths or alternate hashes.
Each accepted Run snapshots the reviewed recipe and effective permissions.
Shared-model installation requires an authenticated administrator and
`manage_models`, with explicit network/filesystem authority. Physical model
resources are shared; users' download history, prompts, Runs and credentials
retain existing ownership boundaries.

Every weight file pins SHA-256, byte length and canonical HTTPS sources. Prefer
publisher URLs with immutable repository commits. Expired redirect URLs are
resolved again from that canonical source; approved mirrors must yield exactly
the same bytes/hash. Source discovery can propose a new URL for that same
identity, but cannot silently substitute another revision or unverified weights.
Show gated or unavailable sources accurately, and retain existing-file import.
Model license information is distinct from the platform's own license.

Starter metadata was checked on 2026-10-30 against the quantizer's
[Hugging Face repository](https://huggingface.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF/tree/c9e90669eeb205d5af35c28a3e9983fc9293c2ec)
and the original publisher's
[configuration](https://huggingface.co/huihui-ai/Huihui-Qwen3-4B-Instruct-2507-abliterated/blob/c9bd464550d4078c72af0dd22aa18d0437868ce3/config.json)
and [model card/license declaration](https://huggingface.co/huihui-ai/Huihui-Qwen3-4B-Instruct-2507-abliterated/blob/c9bd464550d4078c72af0dd22aa18d0437868ce3/README.md).
Q4_K_M and Q8_0 have independent pinned file identities. The declared attention
geometry is a planning hint until the downloaded GGUF is actually inspected;
abliteration is not a guarantee about every model response or content policy.
No starter weights have been downloaded by the normal tests.

## Durable download and publication

`model_download_files.py` provides a bounded streaming primitive. Files live in
application-owned `models/store/<sha256>`; intermediate bytes use the same hash
plus `.part`. The API never persists a container-specific `/data` path into a
model record. The worker checks the complete SHA-256 and byte length; typed native inspection
resolves a relative reference under its configured data root, checks immutable
regular-file identity, size/mtime and bounded GGUF metadata before the existing
model definition/load machinery can use it. It cannot become
an arbitrary host-path endpoint or unrestricted model-directory write.

One per-object exclusive file lock fences concurrent workers. Public DNS is
validated and pinned for every HTTPS hop, including redirects; proxies, cookies,
credentials and implicit redirects are disabled. TLS still verifies the original
host. Identity transfer encoding and exact Content-Range/length checks prevent a
resumed response from appending a complete file or mismatched byte interval.
A source without Range support restarts the unpublished partial safely.

Cancellation checks cover DNS, response opening, stalled reads, streaming and
hashing. Partial files are fsynced and retained across cancellation or transport
failure. Complete bytes must pass the pinned hash before publication; bad
unpublished bytes are reset before a retry/mirror. Existing files are verified
and reused, never overwritten as a repair. Symlinks, hard-linked/writable
partials and non-regular files fail closed. Atomic create-without-overwrite and
reconciliation of interrupted publication retain one verified immutable object.

A verified cached object is not an installed capability. The worker must still
serialize Task Stop with registry/receipt publication, verify its frozen catalog
identity and source observation, and persist an inspectable JSON receipt. Lost
acknowledgements must reconcile that receipt instead of repeating downloads,
model loads or runtime installation. Downloaded code is never imported or
executed by the file primitive.

## Implementation sequence and remaining gates

1. Complete and qualify the immutable file primitive and curated source metadata.
   Exercise correct/mismatched ranges, interrupted/stalled transfers, cancellation,
   hash failure, stale URLs, mirrors, concurrent writers and filesystem boundaries
   with tiny fake bytes. Keep incomplete adapters unpublished.
2. Add the owner-bound download executor/API and durable revision/receipt model
   with an Alembic migration where needed. Resume uses the original pinned recipe,
   not current recommendations. Real disk-space checks precede transfer. Publish
   byte progress through the ordinary event stream and Run projection.
3. Add typed app-owned model adoption/inspection to the Runner and bridge it to
   the existing shared ModelFile/Definition and owned llama.cpp load contracts.
   Verify container/host path mapping, permission, cancellation and recovery.
4. Build hardware-aware setup/catalog UI with coherent capability cards and a
   durable installation history. Reuse installed models; separate estimated fit,
   download completion, runtime readiness and actual first inference. Include
   image/video/voice/music/avatar runtime and companion-file recipes rather than
   treating a GGUF file as a complete multimodal installation.
5. Package the launcher and pinned runtime preparations, then qualify clean Linux,
   Windows and macOS journeys. Add release-specific operator workbook cases,
   actual platform evidence, update/uninstall preservation and documentation.

Private source/check evidence lives under
`data/acceptance/guided-model-setup-20261030/`. The normal file tests use temporary
storage and mock HTTPS only; they consume no GPU, real model download or cloud
inference. Remaining steps are required before NR-13/14 can be marked complete.

### Registry and job implementation decision

The install workflow will use the existing owned Task/Run/event records and
idempotent submission receipts rather than a second job queue. Resume keeps the
original catalog snapshot and publishes a new attempt under the same Task.
Only an app administrator may create/resume these shared-model mutations.

Migration 0042 adds an optional app-data-relative location and checksum to
ModelFile, preserving external host paths as the other exclusive coordinate.
App-owned files never inherit a guessed host path. Source helpers keep legacy
host Run payloads unchanged, while typed Runner requests explicitly mark an
app-owned `models/store/<sha256>` reference. The Runner resolves only this fixed
namespace under its configured data root, checks regular/read-only file identity,
size/mtime and bounded GGUF metadata, and never downloads or runs a caller URL.
Full SHA verification belongs to the cancellable download worker; the native
metadata inspection must not be described as an independent full-file hash.

### Qualified Linux conversation-model candidate — 2026-10-30

`Models → Set up a local model` (`/setup/models`) shows detected RAM/GPUs,
application-volume free storage, Q4_K_M/Q8_0 choices, size, pinned source/license
and an estimated fitted context with GPU headroom. An authenticated administrator
accepts the license and starts an owned download Task. Ordinary members can use
shared installed models but cannot mutate installations or inspect someone
else's download Runs/receipts. Stopped attempts and worker loss require explicit
Resume against the last attempt; the frozen recipe and cached bytes survive.
Files-only preparation is explicit on hardware that cannot run this CUDA profile.

A real isolated Linux qualification downloaded the pinned **2,497,281,312-byte
Q4_K_M** through public HTTPS, stopped after **18,874,368 bytes**, resumed, verified
SHA-256, inspected the actual GGUF with the native Runner, adopted a portable
ModelFile/Definition, and opened an empty local conversation from the compiled
UI. A separate worker then loaded the already-installed llama.cpp CUDA image on
one detected RTX 3060 with **32,768-token Q8 KV context** and returned exactly
`local setup works.`. The owned test runtime was stopped afterward. The complete
journey took about 135 seconds on this workstation/network; this is not a general
download/inference benchmark. Desktop/mobile screenshots and proofs are private.
Production data, external roots and existing models were untouched.

This qualifies that exact Linux/model/image route. Q8_0 has mocked contract
coverage and pinned publisher metadata but no fresh full download/inference
qualification. Required remaining NR-13/14 work includes runtime preparation for
a clean installation, media/companion recipes, advanced model discovery, desktop
packaging and actual Windows/macOS clean-install/update/uninstall qualification.

### Next implementation: clean-machine runtime preparation

The next feature branch starts from deployed PR #530. A private read-only probe
first separates a missing image, an unreachable Docker daemon, a mismatched
manifest/platform and an actually present pinned image. It never equates image
presence with working GPU inference. The first Linux NVIDIA recipe pins the
exact `ghcr.io/ggml-org/llama.cpp@sha256:95cdc1510dbc5bc15735529353d72ace9fc96b9aeb0dd6c4cdaf1a6b3f70776f`
manifest used by the real guided-model qualification. Unknown image IDs, source
URLs, commands and mutable tags cannot be supplied by API clients.

Complete the following before publishing an installation action:

- An administrator reviews the native recipe, runtime license, expected storage
  and network use. An owned ordinary Task/Run freezes its recipe hash, deadline,
  effective permissions and idempotent receipt; existing download/account history
  and Task Stop are reused. Inspection stays distinct from mutation.
- Only the native Runner may prepare the fixed pinned image. It must not retag,
  replace or remove an operator's configured image, alter Docker/driver settings,
  change external runtimes or receive arbitrary image/CLI arguments.
- A subprocess PID is not enough to prove that Docker's daemon-side transfer has
  stopped. Qualify actual request cancellation/daemon completion and lost-response
  recovery before exposing the adapter. Reconcile a completed digest instead of
  pulling again; uncertain operations require inspection. Normal tests use tiny
  synthetic results and managed fake processes; real network tests are opt in.
- Native verification/load resolve a prepared recipe consistently while retaining
  existing configured-image behavior and legacy request hashes. Newly prepared
  image presence is followed by actual GPU capability/load/first-result checks.
- UI shows runtime preparation before weights on a clean station, durable progress,
  Stop/Resume and an understandable failure/recovery path. Preserve all existing
  models, account data and device credentials across upgrades.

The new runtime recipe/inspection module is not registered as an install API.
No runtime install/pull capability is claimed until those contracts pass. Linux
x86-64 CUDA qualification does not imply macOS/Metal or native Windows readiness;
those routes and all multimodal/companion-file recipes remain required.
