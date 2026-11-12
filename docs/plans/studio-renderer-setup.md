# Guided Studio export preparation

Studio must prepare its CPU renderer through the existing administrator-owned
runtime Task/Run lifecycle. The control plane receives no Docker socket, shell,
image reference or host path. Native operations accept one fixed profile,
immutable recipe fingerprint, Run UUID, deadline and existing setup permissions.
Selection is a private native receipt; render dispatch still uses its own frozen
image/recipe/daemon observation and source/cancellation contracts.

The initial existing-image phase delivered the workstation path: find only existing images carrying
the exact packaged recipe and required entrypoint/user/protocol, then explicitly
activate that verified image through a queued setup Run. Honor explicit native
configuration. Journal intent before atomic selection publication, reobserve a
lost acknowledgement, fence early cancellation and retain completed shared
preparation after a late Stop. Account privacy, administrator revocation,
changed image/recipe/daemon, symlinks and worker/Runner restart require tests.
Readiness must notice a changed selection without a stale cached failure.

The original phase reported fresh installation unavailable when no matching
image existed. The development installer now prepares the fixed packaged
SDK/renderer dependencies in bounded, owned CPU containers and publishes only
a verified result through that same setup Run.
Use pinned official sources/lockfiles, private per-Run staging, no host OS/driver
changes, no GPU/model downloads, no Docker control in the application, and no
unowned BuildKit jobs or broad cleanup. Stop/recovery must confirm exact owned
container cleanup before resources are released. Existing qualified images can
be reused without downloads. Native readiness and full-film quality remain
separate qualifications.

The Studio export panel presents the existing runtime preparation consent,
progress, Stop/resume and logs in human terms. Enable export only after actual
native readiness; never turn an absent engine into fake availability. Complete
new generated reels/films and preserving full deployment remain goal gates.

## Fresh installation: owned-container assembly

The implementation candidate uses two serial, explicitly owned CPU containers,
not an implicit daemon-side BuildKit job. Their official Node/Python manifests
are fixed by digest; the SDK follows the packaged npm lockfile with lifecycle
scripts disabled. The runtime installs the same Chromium, FFmpeg, Pydantic and
Pillow components as the existing finite renderer recipe. No user command,
registry reference, host mount, GPU request or host package installation enters
this operation. Final rendering remains network disabled and non-root.

`motion_prepare_plan.py` defines the closed stage specifications and source
archives. Each stage has a two-GiB equal memory/swap ceiling, two CPUs, a process
limit, private IPC, explicit runc and no-new-privileges. Only the runtime package
stage has the small capability set needed for in-container package ownership.
SDK source archives use root ownership and readable ordinary files inside the
container; private host staging permissions must not break capless npm access.
No SDK archive is extracted onto the host. Ownership validation refuses changed
images, commands, environment, privileges, resources, mounts and shared namespaces.
`motion_prepare_owner.py` journals creation intent before Docker calls, adopts
only the exact stage after a lost reply, and refuses uncertain replay. Cleanup
rechecks the pinned base, daemon, complete inspected policy and container ID
before any Stop/delete, without volume removal. The two modules are bound into
the preparation manifest alongside the native lifecycle and job sources. The
existing setup endpoint now runs this workflow when no compatible image exists.

A private actual assembly experiment completed in approximately 135 seconds,
with both temporary containers verified and removed. The resulting new image
passed an ordinary disposable HTTP → worker → private UDS → renderer → Library
export: six seconds, 180 frames, 1080×1920, two timed presenter intervals and one
calibration soundtrack, complete decode, source lineage and owned cleanup.
This proves actual assembly and rendering, not the complete installer lifecycle
or generated-film publication quality. No new model was downloaded or inferred.
The experiment ran two bounded stages concurrently; the product policy runs them
serially to keep its preparation RAM reservation predictable.

Fresh setup extends the existing owned runtime preparation Run. Its contract is: Freeze the preparation policy,
source archives, official bases and renderer recipe in the accepted manifest.
Persist daemon identity and creation intent before every stage. Reconcile lost
acknowledgements by exact owned name/ID and full inspected policy; never blindly
create another stage. Publish the final verified image and selection only after
successful assembly. Stop/recovery must inspect and clean only owned containers;
uncertain cleanup retains resources. A late Stop retains verified shared images.
Reserve the stage memory plus the native supervisor, retain the four-hour bound,
and report actual stages without inventing download progress. Cover cancellation,
worker/Runner loss, changed daemon/image, early/late Stop, account/admin scope,
symlink storage and a fresh end-to-end setup Run before enabling the UI.

Local qualification of these primitives passes 122 relevant native/backend
checks, including 70 policy/ownership cases. An actual Docker probe additionally
created one unstarted fixed SDK stage, repeated its adoption without another
create, uploaded the canonical source archive and confirmed exact cleanup.
This is narrower than a complete installer lifecycle test.


## Integrated first-use qualification — 2026-11-12

Actual HTTP enqueue → scoped worker → private Unix Runner → fixed native helper
prepared a new engine, verified its identity, cleaned both owned stage containers
and atomically activated it. A further actual typed render using that exact new
image passed 1080×1920/180-frame decoding, audio, source lineage and cleanup. An
actual Stop while a preparation container was running canceled its Run, removed
only owned stages and left rendering unready. An actual crash of both worker and Runner during a confirmed live stage recovered
the same Run and original native helper, completed preparation and cleaned stages
without another installation launch.

These private tests preserve the workstation's existing engines: initial matching
image discovery is hidden only for the disposable station until its own selection
is published. The dependency installation, containers, resource limits, commit,
activation, Stop and rendering are actual operations. Official base images may
be reused from the Docker cache; this is not an empty-Docker-host download claim.

Real qualification caught two faults missed by synthetic Docker fixtures. Docker
changed `OomKillDisable` from false to null after start; restoring only that field
matched the complete original policy hash. The policy now accepts only those two
OOM-enabled representations and rejects true or any other field change. The
image save also exceeded the generic thirty-second HTTP timeout: a successful
actual save took approximately 69 seconds. Commit now uses the smaller of the
remaining deadline and ten minutes, with no second commit after an uncertain
response. Native failure logs retain the error class without registry URLs.

The product executes stages serially, reserves 2304 MiB for the two-GiB stage and
256-MiB helper, and applies a one-hour setup deadline. The UI reports actual
stages and explains dependency downloads; it invents no download-byte totals.
Existing-image receipts keep their original resource/deadline behavior.
