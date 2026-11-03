# Native Linux GPU preparation — NR-13/14

Status: planned, not implemented or qualified. Preserve the working Linux GPU
profiles, Windows owned-guest recipe, ordinary CPU setup and current workstation.

## Observed first-user gap

The Debian installer prepares Docker/Compose and one-time account access, but
does not prepare NVIDIA Container Toolkit on a fresh native Linux host. Runtime
preparation downloads images; it does not repair this host prerequisite. The
clean Ubuntu qualification exercised CPU inference; the actual Linux GPU tests
used an already configured workstation. Neither proves a fresh GPU installation.
The Windows helper explicitly rejects native-host activation and must retain
that guard. Do not invoke it on native Linux to work around the missing flow.

## Intended experience

Support Ubuntu 24.04 x86-64 with a working OS-provided NVIDIA driver and the
system Docker Engine first. Native startup checks graphics prerequisites without
changing them. An already working installation proceeds without an authentication
prompt or software replacement. CPU-only startup keeps its present path.

When preparation is needed, offer **Enable GPU features** and an explicit CPU
choice. Explain the small toolkit installation, Docker configuration and any
required Docker restart before asking for OS administrator authentication. A
canceled prompt leaves the machine unchanged. Application passwords never enter
this flow. Continue into normal model setup only with truthful GPU readiness;
downloading model weights remains a separate reviewed choice.

Existing Docker Desktop/rootless/remote contexts must not be silently replaced.
Existing partial or unknown toolkit/configuration states require inspection;
do not downgrade packages or overwrite another application's configuration.
Missing/incompatible drivers need an actionable OS setup message. Never install
drivers, CUDA toolkits, kernels or model weights in this operation.

## Boundaries and implementation

Extend the existing native installer and root-owned polkit helper pattern, not
the Host Runner API. The Runner remains an ordinary user process. No web/agent
permission, shell endpoint or raw Docker access is added to the control plane.

Reuse the four pinned, publisher-verified toolkit inputs and verifier already
used for the owned Windows guest. Preserve its recipe identities and WSL-only
activation guard. A separate argument-free native Linux helper performs only
the fixed reviewed OS setup, using the same isolated/no-site interpreter and
standard-library trust boundary as the Docker-account helper. It accepts no
command, URL, package choice, caller filesystem destination or target daemon.
Reject WSL/Darwin and untrusted/non-system Docker coordinates.

Revalidate package names/versions/hashes and root-owned inputs before dispatch.
Inspect pinned package maintainer scripts before relying on their service
behavior. Preserve unrelated daemon settings, runc defaults and a private
root-only original configuration receipt; never expose possible proxy/registry
secrets through UI output. Bound operations and retain durable phase/hash
receipts across a lost acknowledgement. Inspect before retrying; do not blindly
undo a package-manager transaction or overwrite later administrator changes.

Do not stop external containers. Docker restart requires explicit prior consent
and a verified idle daemon, rechecked immediately before restart. A newly busy
daemon retains a pending/inspection state instead of disrupting workloads. The
normal user app is never executed as root. Current workstation tests must not
install packages, rewrite daemon settings or restart its Docker service.

Use the bundled application image for a bounded, owned CUDA-driver query with
fixed argv, no model, no network or data mounts. Inspect actual device UUIDs;
an installed runtime entry alone is not GPU readiness. Remove only the exact
owned probe container. The already qualified UUID-selection probe supplies a
reference for compute enumeration, not a new Windows or fresh-host acceptance.

## Qualification before activation

- Normal fake/temporary tests: cancel/refusal, UID and path boundaries, immutable
  inputs, configuration preservation, busy daemon, changed state and lost ack.
- Real disposable Ubuntu OS fixture: OS authentication cancel/accept, actual
  package/daemon setup, retained data and safe repeated inspection. CPU hardware
  observations remain CPU evidence; simulated GPU observations are labeled.
- Existing actual NVIDIA host: read-only healthy-path/probe checks only; no
  package, driver or Docker changes. No repeated expensive inference unless a
  changed contract or failure requires it.
- Fresh actual NVIDIA installation: complete guided model load/reply, Stop and
  restart with retained data before claiming that full hardware journey passed.
- Recheck package inventory, Linux native UI and Windows recipe regressions;
  update the operator QA catalog and installation/readiness claims accurately.

Remain unavailable until the installation permissions, interruption/recovery
and relevant real platform contracts pass. This is a release requirement, not a
new unrestricted system-management capability.
