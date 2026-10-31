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

The initial recipe/inspection checkpoint did not register an install API.
The subsequent integrated runtime candidate is documented below. Linux
x86-64 CUDA qualification does not imply macOS/Metal or native Windows readiness;
those routes and all multimodal/companion-file recipes remain required.

### Runtime protocol checkpoint — 2026-10-31

The next branch now implements a typed native preparation protocol and owned
child, plus the gated control-plane Task API. Native preparation freezes the
profile/hash/deadline, resolves the operator's effective **local Unix Docker
context**, records daemon identity and disk headroom, and never accepts caller
images, URLs or commands. A single owned child streams the fixed image pull
through that Unix API. Structured per-layer observations supply byte progress;
only exact digest/platform verification and an immutable-request receipt permit
success. Cached images are re-inspected and do not launch a process. Metadata
writes use exclusive temporary files, fsync and atomic replacement.

The real Docker 29.1.3 qualification used an owned TLS loopback registry with an
approximately 8-MiB neutral synthetic image. Stop closed its daemon-side transfer,
left the byte count stable and did not publish the image. An explicit new attempt
then survived SIGKILL/restart of the isolated Runner: the original process identity
was inspected, completion was reconciled from its checked receipt despite a lost
waitpid exit code, and cached replay created no new process. Only the uniquely
labeled test image was removed afterward. No GPU, production state, drivers,
Docker configuration or pre-existing images were changed. A separate actual
inspection reconciled the already-installed pinned public llama.cpp image over
the real local Docker API, without a fresh 2.4-GiB transfer. These are distinct
claims; the synthetic test is not a fresh public-image clean-install smoke.

Normal tests cover typed permission/source/deadline rejection, cancel-before-send,
immutable replay, concurrent-profile exclusion, uncertain dispatch, saved log
cursors, receipt reconciliation, filesystem boundaries, and private account-owned
queue/Stop/Resume receipts. The control-plane API is gated by native
`installation_available`, which remains false. The new native install router is
not yet registered in the production Runner app. There is **no operational
end-user runtime installation claim** at this checkpoint.

Remaining integration, on the same feature branch:

1. Add the runtime executor and register it only after contracts pass. It must
   use the saved profile/hash and exact Run ID/deadline, retain structured byte
   progress and log offsets, verify current administrator authority, and publish
   only a checked private JSON receipt under the Task Stop fence. Lost claims
   must not cancel a newer worker's operation or release its reservations.
2. Extend worker-only revoked-operation cleanup, following
   `revoked_private_access.py`, to cancel this exact native operation without
   opening an execution scope for a disabled/demoted user. Preserve leases/RAM
   until native cleanup is confirmed. Add actual admin/member and revocation
   cases, including unavailable Runner and no duplicate pulls.
3. Add the lifecycle executor to safe native-journal reattachment in
   `recovery.py` and queued cancellation handling in `runs.py`; a dispatched
   requeued Run still requires native Stop. Explicit Resume keeps the original
   frozen recipe. Uncertain launches remain inspection-required.
4. Make app-owned GGUF verify/load consistently use a prepared pinned image when
   the operator's configured image is absent. Preserve configured images,
   external model behavior and legacy request hashes. Do not retag an operator's
   image. Qualify actual local model loading/inference with that fallback.
5. Add the runtime step before weight downloads in the existing model setup UI:
   ready existing runtime first, source/license/storage review, durable
   preparation history/Stop/Resume and clear verified-image versus actual-first-
   inference states. Do not introduce a second execution queue or mode switch.
6. Finish native app route registration and availability, affected complete
   test families, compiled private desktop/mobile/API/worker/native proof,
   packaged image/Compose and exact source/bundle review before a `develop` PR
   and preserving-data rollout. Full media/advanced-catalog/platform installers
   and NR-06/07/09 release gates remain in scope.

Docker's documented request-disconnection cancellation contract is described in
[image pull](https://docs.docker.com/reference/cli/docker/image/pull/#cancel-a-pull).
The pinned image's public OCI manifest/layer descriptors were inspected with
SHA-256 verification; its Linux/amd64 child is
`sha256:fd2e46908d509c497115bbec9372f0cc1d658c314b0394a4d190dff9f1c63827`.
Its 13 layer/config objects total **2,589,389,163 bytes**. Private exact-source and
qualification evidence is under `data/acceptance/guided-runtime-setup-20261031/`.

### Integrated Linux runtime candidate — 2026-10-31

The worker now records byte stages/log cursors, keeps a frozen native invocation,
checks live administrator authority and its claim after native I/O, and publishes
a private receipt only under the Task Stop fence. Recovery reattaches the same Run
and native journal. Trusted worker coordination can stop an existing operation of
a disabled/demoted account without granting it another execution session; unknown
cleanup keeps its lease/RAM reservations. Dispatch rejection is distinguished from
a lost acknowledgement. A queued dispatched cancellation still confirms native
Stop. Actual image verification is separate from successful inference.

`Models → Set up a local model` first shows its conversation engine. Existing
images need no replacement download. When required, the administrator reviews
source/component licenses and free runtime storage, prepares llama.cpp, watches
its durable history/progress and can Stop/Resume. Model downloads remain available
as explicit files-only preparation if runtime/hardware readiness is absent.
Previously downloaded files have a separate **Verify model readiness** action;
it reuses metadata verification and never redownloads or starts inference.

A prepared pinned image serves app-owned GGUFs when the configured image is
missing. It also serves discovered models when the missing configured image is
the default server-CUDA tag. Existing images and explicitly configured custom
legacy images remain authoritative; no image is retagged and request hashes of
previously owned containers are unchanged.

Qualification distinguishes three independent proofs:

- Compiled desktop/mobile UI → actual account API → separate worker → native
  process → real Docker transfer against the owned small TLS registry. License
  gating, same-Task Stop/Resume, verified JSON receipt and private history/Run
  denial passed. The neutral synthetic image is not an LLM inference claim.
- Actual installed public pinned image preparation through an ordinary owned
  Task, with the configured image deliberately missing. Real local GGUF replies
  for two private accounts reused one GPU runtime, with 32k Q8 KV context; only
  the owned test runtime was stopped afterward. Verified weights were reused.
- Native SIGKILL/restart retained the owned process, reconciled its checked
  receipt despite a lost exit status and avoided another transfer. No daemon
  configuration, drivers, pre-existing images or production data were changed.

A fresh 2.4-GiB public-image cold-cache installation is not claimed by those
proofs. Clean-machine platform packaging, all media/companion recipes, advanced
catalog discovery and actual Windows/macOS qualification remain NR-13/14 work.
Local review/image/browser source identities and preserving-data rollout are
recorded separately; the final 0.1.0 release gates remain in force.

Local merge checks for this increment use the repository-authorized equivalent
of `check-all.sh`: Python lint/format across 820 files; 266 passing cases across
19 complete affected Python families, followed by 32 final worker/account/model
cases and 68 native/image/source cases after review fixes; 40 frontend cases
across seven complete affected families; frontend format/lint/types/production
build; all 26 QA workbook utility tests; production/development/LAN Compose
configuration; Docker image build and packaged fake API/worker/SSE smoke. Final
package sources and compiled desktop/mobile browser assets are compared with the
reviewed checkout. Existing five React refresh warnings and the bundle-size
advisory remain; there are no lint errors. These checks do not claim a fresh run
of unrelated test families or Windows/macOS acceptance.
