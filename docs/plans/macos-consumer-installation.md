# macOS consumer installation — NR-13/14

Status: implementation contract, not an available Mac installer. The full release
still requires a real local Mac installation and first result; a remote web client,
Linux emulation or an unsigned skeleton does not satisfy it. Preserve the Docker
control plane, native user Runner and Task → Run → Events → Artifacts lifecycle.

## Current code and verified upstream constraints

`scripts/desktop.py` deliberately admits Linux x86-64 only. Its lifecycle control
uses Linux `SO_PEERCRED`; long socket paths use `/proc/self/fd`. Native process
identity and memory scopes also depend on Linux `/proc`, systemd and cgroups.
Removing the launcher's platform check cannot produce a correct Mac package.

Docker's maintainer reports support for shared native Unix sockets with Docker
Desktop 4.87, Docker VMM and its enabled socket-sharing component. This changes
the older assumption that an extra TCP bridge is always necessary. Use an actual
private-socket round trip to verify that installation, rather than trusting a
version string, process name or feature flag. Do not change the user's Docker
backend/settings automatically. [Publisher's report, 2026-08-17](https://github.com/docker/for-mac/issues/483#issuecomment-5318394126).

Ordinary Docker Desktop `--gpus` passthrough is documented for Windows/WSL2,
not native Mac Metal. Local Mac llama.cpp therefore needs a native runtime
adapter; a Linux CUDA image cannot satisfy that requirement. llama.cpp documents
Metal acceleration and an explicit zero-GPU-layer CPU mode. These are distinct
profiles, never an invisible fallback. [Docker GPU scope](https://docs.docker.com/desktop/features/gpu/),
[llama.cpp Metal build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#metal-build).

## Delivery sequence

1. **Private lifecycle primitives.** Retain Linux peer authentication and add
   Darwin's kernel-provided effective peer credentials for both desktop clients
   and servers. Use a short, owned private runtime directory and the actual
   Darwin socket-length limit; never emulate `/proc`, trust a claimed UID or
   disable authentication. Keep the Mac application unavailable until the later
   gates pass. [Apple getpeereid contract](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/getpeereid.3.html).
2. **Container-to-host transport experiment.** On an actual Mac, bind a private
   native test socket, mount only its owned directory into a fixed reviewed
   container and perform a bounded nonce exchange in both directions. Verify
   byte transport, permissions, restart and rejection of other OS users. Do not
   mount the Docker socket or host home. Successful file sharing alone is not a
   Runner transport result. Verify the native/container UID mapping, SQLite WAL
   locking and canonical artifact paths on the actual shared filesystem as well.
   If this transport fails, stop setup with an actionable
   local prerequisite; design and review an authenticated alternative separately,
   without an automatic public/TCP listener.
   Retain the existing typed Runner completion proxy: the native model socket
   stays on the Runner side and needs no new container mount or TCP bridge.
   Qualify that separate native inference connection, its short owned runtime
   directory and the pinned build's socket arguments; one successful transport
   probe does not qualify it. Long Application Support data paths still belong
   in the shared-filesystem experiment. Never bypass canonical path checks with
   an unchecked alias or assume relative socket names work.
3. **Native process/resource adapter.** Separate platform-specific ownership,
   start identity and memory observation from executor logic. Reuse owned process
   groups, durable journals, deadlines, Stop and recovery. Darwin must not import
   Linux `/proc`/cgroup assumptions or signal an unverified reused PID. Measure
   unified-memory headroom, context/KV overhead and runtime contention. Do not
   report dedicated VRAM or a Linux hard zero-swap limit for unified memory.
   The native read-only telemetry branch uses fixed public Mach CPU/VM queries
   and `hw.memsize`/`vm.swapusage`. It reports only actually free pages as its
   conservative available RAM observation, without adding inactive, purgeable,
   speculative or compressed counts that can overlap. Used RAM means total
   minus those free pages, including cache. Unavailable sensors remain null.
   This observation is neither a hard resource limit nor a Metal memory budget;
   no NVIDIA devices or CUDA/Metal capability are inferred from system RAM.
   Normal Linux observations and their admission rules remain unchanged.
   [Public VM layouts](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/vm_statistics.h),
   [CPU/host layouts](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/host_info.h),
   [swap layout](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/sysctl.h).
4. **Local llama.cpp CPU and Metal.** Add independently pinned Darwin binaries,
   architecture/minimum-OS/source/hash/license receipts and compatible verified
   GGUF catalog profiles. Native dispatch constructs fixed argv and private local
   inference endpoints; callers cannot choose binaries, commands or arbitrary
   filesystem paths. Model load, readiness, tokens, Stop and recovery remain
   ordinary owned Runs. Register shared model/runtime resources without exposing
   private conversation or setup identities. Qualify Apple Silicon and Intel
   independently; an arm64 result does not qualify Intel or every media engine.
5. **Native package and guided first run.** Build a real application bundle with
   bundled Python, required native wheels, exact control-plane image and native
   launcher. Use the existing compiled web UI, account bootstrap and hardware/model
   setup. Own data lives outside replaceable code under Application Support;
   retain relative domain paths. Present Docker's own prerequisites/license and
   OS consent explicitly; no end-user Homebrew, Python, Node, terminal commands
   or manual `.env` editing in the qualified happy path. No root application,
   global settings changes or removal of another Docker installation.
6. **Preserving update, removal and signing.** Transfer the exact reviewed bundle,
   validate inventory and retained owner/instance, stop normally, back up and
   migrate data before atomic activation. Retain the original configuration and
   refuse a second live owner or changed identity. Removing the application keeps
   accounts, models and artifacts by default; data removal is a separate explicit
   action. Public distribution needs Developer ID signing, hardened runtime,
   notarization and a stapled ticket, with real Gatekeeper acceptance. Signing
   credentials stay outside Git and application data. [Apple distribution guidance](https://developer.apple.com/documentation/xcode/preparing-your-app-for-distribution),
   [Developer ID](https://developer.apple.com/developer-id/).

## Acceptance evidence

### Owner-dispatched public Mac checks

The repository is now public. GitHub documents standard public-repository runners
as [free and unlimited](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The existing manual workflow gains `operation=macos-native-checks`, restricted to
the owner and a public repository before runner allocation. It uses only fixed
standard `macos-15` ARM and `macos-15-intel` labels, read-only repository permission
and a 20-minute bound. Ordinary CI/release jobs do not run for this operation.
It creates no uploaded artifacts/caches or larger/paid runner allocation, changes
no billing setting and does not run on push or pull requests automatically.
The native check lock contains the full Runner/developer and packaging dependency
graph at the existing pinned versions. It does not install the control-plane/Linux
media-QA environment on macOS: its optional ONNX Runtime pin has no Intel Mac wheel.
That separate media runtime is not qualified or advertised by these kernel/import
checks. All four selected native test families run unchanged on both architectures.

The operation opts kernel ownership, CPU/RAM and Metal **observation** tests into
actual native APIs, then assembles the pinned Python layer and executes its exact
isolated interpreter. It verifies native imports, source Runner import, a tiny
synthetic native FFmpeg audio round trip and unchanged layer bytes. Reports use
only controlled public-fixture/platform/version/source facts, with no user data,
credentials, real model, GPU inference or release/deployment. Successful hosted
checks do not qualify Docker Desktop socket sharing, Metal inference, Gatekeeper,
the GUI installer or a complete station journey. Retain exact job/head/results
before claiming any native acceptance. Account/service refusal is not a pass and
must not be worked around by selecting a paid runner or weakening a failed test.

### Native llama.cpp byte preparation

The internal offline assembler pins [llama.cpp b12032](https://github.com/ggml-org/llama.cpp/releases/tag/b12032)
at source `dde879bc4f954b809892fd0d660515f42536394a`. Both public archives
were downloaded and independently hashed before reviewing their complete file
inventories and Mach-O load metadata. ARM64 is 16,513,842 compressed bytes with
SHA-256 `00468fe833eb000b78a748122f5921b6c7b07dc82331a8d0c68196c69cb26382`;
Intel x86-64 is 12,258,802 bytes with SHA-256
`291d99f3b6f45f67f73afe5381540f29928840a1a14d9c19d6595bd649a035fc`.
These binaries declare macOS 13.3 as their minimum. The ARM archive contains the
Metal backend; the Intel archive is CPU-only. Do not infer Intel GPU support
from a successful Metal hardware observation. ARM's system RDMA dependency is
weak-linked, rather than a required external/Homebrew installation.

Preparation reuses the existing immutable store, canonical private directories,
fingerprints and cooperative deadline/cancellation checks. It copies only the
reviewed server, libraries and license; in-tree library aliases become controlled
hardlinks to the same immutable file, and command utilities are omitted.
Exact source/output hashes, architecture, minimum OS, executable permissions,
library dependencies/search paths and the complete output inventory are verified.
No archive path or link can publish outside the new owned operation directory.
The v2 candidate retains alias file identity because
[dyld checks existing file identities](https://github.com/apple-oss-distributions/dyld/blob/main/dyld/Loader.cpp)
when handling alternate library paths. Its exact in-bundle link counts and shared
device/inode groups are verified; an external hardlink or independent alias copy
is rejected. This also avoids duplicate library storage. The earlier unqualified
v1 recipes/prepared directories are retained, without overwrite or activation.
Interrupted/changed operations remain for inspection instead of being overwritten;
a final receipt is published only after complete verified byte assembly.

The private receipt uses app-data-relative paths and explicitly records
`inference_qualified=false`. Shared runtime observations must not expose its
private setup-operation coordinate. Existing Runner runtime-selection APIs still
reject these unqualified profiles. This module executes/downloads nothing and
does not remove quarantine, sign binaries, alter Docker/OS settings, or install
an available Mac application. Native launch, memory admission, owned Stop/recovery,
local inference transport, signing and complete Mac consumer acceptance remain
the next execution/package gates. Byte assembly can be tested on a Linux package
builder; that result is not Mac inference evidence.

Normal tests use synthetic native bytes and malformed archives. The opt-in
`AI_STATION_REAL_MAC_BUNDLE_TESTS=1` with `AI_STATION_MAC_BUNDLE_CACHE` pointing to
the already verified archives checks both actual distributions without network,
native binary execution or model weights.

Initial byte preparation passed 225 affected tests across twelve families, plus
two opt-in assemblies of the actual ARM/Intel archives. Whole-tree Ruff/format
checks cover 971 Python files. The Linux builder verified 37 ARM and 34 Intel
immutable output files and their native load metadata; it did not execute them.
The v2 alias-identity correction passes 227 affected tests and both actual archive
assemblies; independent-copy and outside-hardlink changes are rejected.

### Internal native inference lifecycle candidate

`darwin_llama.NativeLlamaManager` now composes the existing immutable SDK/model
boundaries, GGUF context inspection, Darwin ProcessManager and completion proxy.
It is internal: no normal Runner route, catalog profile or consumer launcher
selects it. `inference_qualified` remains false until actual Mac acceptance.

The frozen request selects matching macOS 13.3+ architecture, CPU or one observed
unified Metal device, exact owned model/context/RAM estimate and an absolute
startup deadline. Fixed argv uses the pinned source's `MTL0` device name for that
single Metal device, or `--device none`, zero GPU layers and no KV offload for CPU.
Both use offline mode, disabled automatic fit, one slot and Q8 KV caches. The
Intel archive cannot admit Metal. No binary, command or model URL is caller chosen.

Admission includes model bytes plus a 15% weight margin, inspected full-context
Q8 KV/state geometry and 1 GiB headroom. It compares actual conservative free RAM
and retains other live/uncertain reservations; this deliberately double-counts
already allocated resident memory rather than promising aggressive packing.
Metal also needs its exact registry identity, complete unambiguous inventory and
sufficient advisory working set. This is admission, not a hard allocation limit
or a no-swap guarantee; those facts remain explicit in every safe projection.

Durable dispatch fencing precedes exec. A lost acknowledgement attaches the same
owned process or requires inspection; it never starts a second model. Stop intent
persists before signaling and a replacement observer delivers it. Startup timeout,
wrong alias/context and invalid/oversized readiness metadata stop only the owned
group. The startup deadline survives replacement; reaching ready does not create
an artificial maximum model lifetime. Unknown ownership retains its reservation.

Inference uses a short canonical, owned mode-0700 socket directory and a private
Unix socket; HTTP proxy environment and redirects are disabled. The shared model
inherits only fixed per-instance environment/cache paths. Its stdout/stderr are
discarded at process creation, preventing another user's prompt or response from
appearing in the loader owner's Run log. Ordinary executor output stays captured.
The privacy policy is durable and cannot change on an idempotent process retry.

Normal lifecycle tests use real disposable Linux processes and private sockets,
real bounded GGUF headers and simulated native/SDK facts. They exercise readiness,
streaming, ownership denial, acknowledgement loss, Stop/replacement, deadlines,
RAM/Metal contention and privacy. These results do not qualify Mach-O execution,
Metal inference, shared Docker Desktop transport, Gatekeeper or a complete Mac
installation. Actual hardware, package integration and signing remain required.

### Native Python packaging layer

The package builder now has separate fixed CPython 3.12.14 distributions and 26
hash-pinned wheels for Apple Silicon and Intel, using the existing Runner/native
dependency versions. Publisher input coordinates are in `packaging/macos/`.
The Python archives come from the
[20260901 standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901);
wheel files/versions/sizes/hashes were selected from their official PyPI release
metadata. No source build or target interpreter execution is needed on the builder.

The selected [PyAV 19.0.1 files](https://pypi.org/project/av/19.0.1/#files) require
macOS 14 for Apple Silicon; that layer's minimum is 14.0. The Intel layer retains
13.3, matching the native model SDK's floor. These are layer minima, not a complete
consumer compatibility claim: Docker Desktop/bridge and application acceptance
may require a newer OS and remain separate gates.

`PYTHONPATH=host-runner:scripts python scripts/macos_desktop_python.py
--architecture arm64 --cache /absolute/owned/cache --output /absolute/new/python`
assembles only previously verified immutable inputs. The cache and output parent
must already exist. Explicit `--download-inputs` permits fetching only the built-in
public archives/wheels (59,430,685 compressed bytes for ARM; 75,088,774 for Intel,
with common wheels reused). It never downloads models or changes the host Python.

The builder reuses safe Python archive extraction and immutable object verification.
Cross-target wheel installation is offline, no-index/no-dependency-resolution,
hash-pinned and binary-only, with an isolated build environment. Build-path console
scripts are omitted. Mach-O thin/universal slices and their actual minimum-OS
commands are checked before publication; Linux/foreign/ambiguous/newer-OS binaries
are rejected. Older compatible minimum-OS libraries are valid: the pinned Intel
NumPy wheel contains a GCC runtime whose legacy minimum is 10.8. A complete file
inventory and final receipt publish only after all output bytes verify. Existing
outputs are not overwritten; failed publication is retained for inspection.

Both actual layers have been assembled on the Linux builder: 3,687 files/130 native
files for ARM and 3,688/134 for Intel. Installed distribution metadata has no missing
or conflicting declared dependencies for the selected Mac targets. This is actual
byte assembly, not execution/import qualification: the receipt explicitly retains
`native_mac_code_executed=false`, `python_import_qualified=false` and
`macos_installer_qualified=false`. The application bundle/launcher, exact target
control-plane image, native imports, GUI/update/removal/signing and full consumer
journey still require implementation/integration and actual Mac evidence.

### Developer native inference qualification command

On a native macOS 13.3+ host, the installed developer Python environment can run:

```sh
PYTHONPATH=host-runner:scripts python scripts/macos_inference_probe.py \
  --data-root /absolute/private/fixture-data \
  --output /absolute/private/new-proof \
  --model-sha256 <verified-GGUF-SHA256> --compute cpu \
  --run-native-inference
```

Use a dedicated private fixture data directory containing only the previously
obtained immutable `models/store/<sha256>` inputs: the matching pinned SDK archive
listed above and a supported GGUF. The tool downloads nothing and verifies the
entire model hash as well as native engine bytes. It rejects existing runtime
storage, reused proof directories, root execution, other platforms and unsupported
architectures. A concurrent runtime claim fails without adoption or cleanup.
Do not point it at a running/previous station or move its models to make this pass.
The dedicated inputs/root and private proof remain after the experiment; failed
or interrupted experiments require inspection rather than automatic replay.

`--compute metal` separately exercises the reviewed Apple Silicon/single unified
device path. Intel accepts CPU only. `--context-size` defaults to 4096; explicit
larger context still needs actual GGUF geometry and fresh RAM admission. The tool
does not change swap/OS policy or claim a hard memory ceiling. Models may use
native CPU/Metal resources only after the explicit inference flag is supplied.

The probe prepares only its pinned engine, waits for exact alias/context readiness,
obtains a bounded complete SSE reply, replaces the manager object while retaining
the original PID, obtains another reply and stops only that owned instance. A
confirmed Stop removes only the newly created short private socket directory;
uncertain ownership/Stop retains it with a private inspection proof. The report
stores response lengths/hashes rather than text, OS/architecture and source/input
identities, and never raw upstream errors. A native-model pass still explicitly
records `macos_installer_qualified=false`, `cross_process_restart_tested=false`
and `other_os_user_tested=false`. It does not qualify Docker Desktop transport,
a complete station/process restart, GUI installation, updates or Gatekeeper.
Ordinary Ctrl+C/SIGTERM attempts that same scoped Stop before exit. A hard crash
still requires inspecting the retained instance/process journal and private proof;
the command never deletes uncertain resources or repeats inference automatically.

Normal tests simulate native inference/SDK/platform facts and test this command's
protocol, refusal, cleanup and evidence rules. No actual Mac run is claimed by
those tests. Run the separate kernel/bridge probes and complete consumer journey
on actual hardware before enabling any Mac installer or catalog capability.

### Native observations and ownership

Native hardware snapshots now include a separate `metal` observation on Darwin.
It enumerates all devices through fixed OS Metal/Foundation/Objective-C symbols,
with a stable registry identity, bounded name, actual unified-memory flag and
optional recommended working-set size. A successful empty array means no device
was available; failed inspection remains unavailable, while missing optional
properties remain null/partial. Metal devices do not enter the existing CUDA
`gpus` list or authorize NVIDIA image/model profiles.

Apple describes [the working-set value](https://developer.apple.com/documentation/metal/mtldevice/recommendedmaxworkingsetsize)
as performance guidance. It is neither free/dedicated VRAM nor a hard memory or
no-swap limit. [Unified memory](https://developer.apple.com/documentation/metal/mtldevice/hasunifiedmemory)
shares CPU memory; do not add it to physical RAM or subtract this probe's own
allocations to invent a system-wide free GPU budget. Native admission must still
combine model/context overhead, current RAM/pressure and durable reservations;
inference/readiness and memory enforcement are separate unqualified contracts.

Framework loading is isolated in a fixed, five-second, no-site Python child.
Only the installed observer file runs, with no caller-selected command/argument,
inherited application secrets or raw diagnostic output. Output is bounded and
validated; timeout, crash, malformed/duplicate identities or incomplete ABI facts
cannot become successful empty hardware discovery. Each probe releases its copied
device array and local autorelease pool. It requests no shader/buffer creation or
model execution, changes no OS setting, and requires no end-user SDK or PyObjC.

`python -m ai_station_runner.darwin_metal` is a developer read-only observation,
not the consumer installer or proof of Metal inference. Native qualification is
opt-in: `AI_STATION_REAL_MAC_METAL_TESTS=1 python -m pytest -q host-runner/tests/test_darwin_metal.py`.
Normal tests simulate the native ABI and probe protocol; their real isolated Linux
child is only a negative-platform control. Actual Mac hardware remains untested.

The native process candidate extends the existing ProcessManager through narrow
boot/capture/liveness/launch hooks; it reuses the same journal, idempotency,
deadline, cancellation and recovery implementation. Normal Runner construction
continues to select the qualified Linux manager. The Darwin class is an internal
candidate, not an exposed capability or a new execution engine.

Darwin launch starts a fixed isolated Python barrier in its own session. It
cannot exec the already-validated workload until the parent captures its actual
kernel identity and durably writes the ownership record. EOF/timeout/failed
publication exits without executing the workload. This prevents fast group
leaders disappearing before their start identity is recorded. Darwin journals
keep a versioned native identity, never Linux start ticks. Only matching boot,
effective UID, start time, group and session authorize cancellation; surviving
group members require bounded native enumeration and independent snapshots.
Denied or truncated enumeration requires inspection, rather than reporting the
group gone. The barrier is native lifecycle code, not an HTTP/agent shell tool.
Real Mac Stop/deadline/recovery qualification is still required before selecting
this adapter in the consumer launcher; memory policy and Metal remain separate.

The independent read-only Darwin identity probe reads a fixed kernel boot UUID and the public
`PROC_PIDTBSDINFO` ABI, including the effective UID, group and microsecond process
start identity. A second snapshot brackets session lookup to reject PID reuse or
changed ownership/group. Missing, denied or incomplete observations are errors,
not successful empty process discovery. This does not itself authorize a signal
or qualify group recovery. Linux boot-identity preflight must finish before
launching a subprocess, so a missing identity cannot leave an unrecorded child.
No Linux journal field is reinterpreted as a Darwin timestamp. Consumer selection
still requires actual native Stop/deadline/descendant/recovery and memory gates.
[Apple process-info ABI](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info.h),
[libproc query implementation](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.c),
[kernel boot-session query](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sysctl.c).

On a native Mac, developer self-inspection is
`python -m ai_station_runner.darwin_process_identity`. It accepts no target PID
and launches no workload. The native self test runs only on Darwin; simulated ABI
tests elsewhere are not a Mac acceptance result. A sandbox/OS denial remains an
inspection error; do not replace the boot UUID with wall time or an invented ID.

`AI_STATION_REAL_MAC_PROCESS_TESTS=1 python -m pytest -q host-runner/tests/test_darwin_processes.py`
opts the shared candidate lifecycle cases into actual native kernel observations.
Those cases launch only short disposable Python fixtures, not models, the UI or
an agent. They check gated publication/failure, idempotency, record restoration,
owned Stop, reused-PID denial, deadlines and a surviving descendant. In normal
Linux tests the same cases use explicitly simulated Darwin facts and real owned
Linux processes; they are a protocol control, not native Mac qualification.

Record actual OS/architecture/Docker backend and immutable package/runtime/model
identities. Exercise clean machine → ordinary-user install → first admin → guided
hardware-fitting download → local streamed response → owned Stop → restart → same
account/history/model → update → same private data → uninstall/reinstall. Confirm
A/B/admin isolation and independent browser sessions, native keyboard/accessibility,
bootstrap-link secrecy, occupied-port/duplicate-click behavior and other-user
socket denial. Stop/recovery must retain exact process ownership; no global Docker
restart, forced agent termination or deletion of unrelated resources to pass.

Linux unit tests can verify parsing, denial, policy and package construction. They
cannot qualify native peer credentials, a Docker Desktop socket mount, Metal,
Gatekeeper or the complete Mac journey. Unsupported capability cards remain
unavailable until their real platform/runtime/profile contracts pass. Export the
remaining cases in the release QA workbook and retain failures as failures.

## Private bridge qualification command

Run `python scripts/macos_transport_probe.py --output /path/to/private-qa/fresh-proof`.
Its parent must already be owned and not shared writable; the proof directory
must be new. This is a developer experiment,
not the unfinished end-user Mac installer or a new Runner/agent tool.

The command admits only an ordinary native Mac user and a local `desktop-linux`
Unix endpoint whose engine reports Docker Desktop and the native architecture.
It never changes context/backend, daemon settings, OS permissions or drivers.
Its fixed Python fixture binds one owned socket directory read-only and a
separate synthetic data directory; there is no Docker socket, host home,
network, GPU request or privileged container. Only its exact labeled containers
can be stopped/removed after ownership checks. Failed/uncertain creation retains
a private pending proof and its temporary root for inspection, without replay.

Two fresh clients exchange nonces through a private native socket. They verify
native peer UID, a long-path artifact, SQLite WAL transaction visibility and
actual competing-writer rejection, then rebind/reconnect and read the retained
data. Neither these checks nor a Linux control proves other-OS-user isolation,
the separate inference path, a complete station restart, Metal or installer
readiness. The result always records `macos_installer_qualified=false` and
`other_os_user_tested=false` for those remaining gates.

The fixed multi-architecture Python index is pinned in source, together with
its amd64/arm64 manifest and configuration identities. This permits the same
reviewed bytes in classic and containerd image stores; a different image or
architecture is rejected. `--prepare-image` explicitly permits fetching that
fixture if absent (about 43 MB compressed); otherwise no download occurs.
Container creation uses `--pull never`. No model weights are involved.

Normal tests use the same client in independent local Python processes and
simulated Docker results, with real file/socket/WAL operations. Actual Linux
Docker control is separately opted into with
`AI_STATION_REAL_TRANSPORT_CONTROL_TESTS=1`; it is not Mac evidence. The actual
Mac test requires `AI_STATION_REAL_MAC_TRANSPORT_TESTS=1` on a native Mac with
the reviewed image already prepared. Retain its proof before enabling any Mac
consumer path. [Python fixture publisher](https://hub.docker.com/_/python).
