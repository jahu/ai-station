# Guided CPU conversation setup (NR-13 / NR-14)

Status: planned implementation and source qualification. This does not claim a
CPU-first installer, clean-machine journey or Windows/macOS support is ready.
Preserve the already qualified CUDA flows, all existing source/Run identities,
configured external images/servers and the shared-model/private-history boundary.

## Problem and intended journey

The current guided catalog recommends only GPU groups. Existing manual native
loads can request no GPUs, but the installer offers only the CUDA runtime recipe
and does not qualify a complete CPU-memory budget. A machine without a compatible
NVIDIA device cannot finish the guided first-conversation flow. This also blocks
meaningful clean consumer VM qualification on a supported Linux CPU profile.

Offer **Local conversation · CPU** clearly when no compatible GPU is present.
Explain that it is slower and uses system RAM before accepting installation.
Start with the existing reviewed small Q4 weights and a conservative context.
Never turn a failing GPU job into a CPU job invisibly, select cloud inference or
mislabel an unsupported AMD/Intel/Metal accelerator as CUDA. Existing servers and
manual choices remain usable. Onboarding must proceed through ordinary model
preparation, selected Chat, a real reply, scoped Stop and retained account/history.

## Runtime and isolation

Reuse the existing typed runtime preparation, download verification, owned native
Docker supervisor and llama.cpp bridge. The upstream
[Docker documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)
identifies a separate CPU server image. Source selection on 2026-10-31 resolved
its Linux/amd64 descriptor to
`ghcr.io/ggml-org/llama.cpp@sha256:c50671c463e746cdccf2c6e77ffd6d77dca2e95290e54ca5ba5c7f524c33e234`.
This is a selected candidate, not an installed or qualified recipe. Freeze its
actual manifest/config, platform, entrypoint, source revision and CLI support
before adding a built-in `llamacpp-cpu-linux-amd64-v1` profile. No moving tag,
caller-selected image, host shell, extra public listener or Docker mount in the
control plane. Preserve configured image priority for legacy dispatch.

The managed CPU profile must be explicit in frozen preparation/definition/load
metadata and in readiness/UI. Ordinary legacy requests must retain byte-identical
serialization when the optional new profile/budget is absent. Do not rewrite
existing shared definitions or silently change a working GPU preset on upgrade.
A shared existing source with an incompatible saved preset needs an explicit
review/use-existing action; matching file bytes alone does not authorize replacing
a shared runtime configuration. Model-file identity remains separate from the
selected execution preset.

Use no GPU device request, no CUDA weight/cache offload and no implicit GPU
visibility. Retain the private model Unix socket, readonly exact model mount,
non-root container, no network, dropped capabilities, owned deadline and process
identity. Stop/recovery must continue to inspect the same owned container.

## CPU memory admission

Reserve durable system RAM before launch. Include complete model weights, actual
GGUF Q8 KV bytes for the selected context, recurrent-state reserve, runtime and
activation headroom. Bound the initial profile and context rather than claiming
GPU estimates also work on RAM. The native request must carry/recheck the exact
managed CPU budget and enforce container memory plus equal memory-swap limit.
Release reservations only after owned cleanup is confirmed. Resource waits,
user Stop, owner revocation and lost acknowledgements reuse existing contracts.
Do not weaken or disguise the old manually configured CPU path as newly qualified.

The catalog's hardware observation must distinguish missing telemetry, inadequate
RAM, CPU-only fit and accelerator fit. A CPU recommendation is a visible reviewed
choice, not a hidden retry fallback. Keep all prior model manifest identities and
Resume snapshots intact; extend optional metadata with omitted legacy defaults.
Native GGUF inspection remains authoritative for architecture/cache/state geometry.

## Implementation sequence and gates

1. Inspect the pinned CPU image and CLI in an isolated, readonly, network-disabled
   container without mounts/models/GPU access. Record the exact image observation.
2. Add the fixed typed CPU preparation recipe through the existing lifecycle.
   Cover digest/platform mismatch, admin/license gates, Stop, journal adoption,
   revoked-owner cleanup and native restart without replaying side effects.
3. Add CPU-specific sizing/selection and frozen load profile plus RAM reservation
   and native enforcement. Preserve old CUDA/configured-image requests and all
   catalog identities. Test insufficient RAM, changed budget/profile and cleanup.
4. Add the plain-language onboarding choice and small-model path. Retain normal
   shared model metadata/private setup receipts and selected-model Chat behavior.
   Do not add a second execution engine or expose technical setup to the happy path.
5. Qualify a fresh isolated account with CPU hardware discovery, verified cached
   small weights, actual no-GPU inference, final text, reload/Stop/recovery and
   second-account denial. An experiment on this workstation must explicitly
   disable GPU access; it is not yet a clean-machine hardware claim.
6. Build/review/package the exact candidate; exercise the real desktop package in
   a suitable isolated clean Linux environment with first result and preserving
   update/uninstall. Do not alter this workstation's Docker/drivers/OS settings
   to manufacture that acceptance. Keep Windows/macOS transport/installation and
   native hardware qualification open until their real journeys are proved.

This increment advances the full consumer goal; it does not replace the required
Linux/Windows/macOS installation, broader accelerators/catalog, expressive media
acceptance, naming or final operator QA workbook. Private source/experiment evidence
belongs under `data/acceptance/guided-cpu-conversation-20261031/`.

## Current source/budget checkpoint

The exact CPU image was pulled and inspected: Linux/amd64, entrypoint
`/app/llama-server`, version b12019, upstream source
`1052f7e1d62611d328ccc65d38c77cd194ee59fc`. Its actual help command completed
inside a readonly, no-network, no-GPU, non-root 384-MiB/zero-swap container with
no host/model mounts. The existing private Unix-socket, Q8 cache, reasoning and
fixed-context CLI flags are present. This does not establish model inference,
CPU-feature portability or full runtime lifecycle qualification.

The unregistered `cpu_runtime_profile` candidate freezes this source and keeps
`QUALIFIED=False`. Its bounded integer memory estimate covers 115% of weight
bytes, complete native-inspected Q8 cache, recurrent state and a separate GiB of
runtime headroom, rounded up. It rejects unverified/invalid dimensions, excessive
weights/context, booleans and nonfinite values. The scoped `scripts/check.sh`
gate passes 23 new cases plus Python lint/format. Reservation, container memory
enforcement, typed dispatch, preparation, onboarding and actual CPU inference
remain the next implementation work; the helper is deliberately unregistered.
