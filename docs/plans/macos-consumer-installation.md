# macOS consumer installation — NR-13/14

Status: implementation contract, not an available Mac installer. The full release
still requires a real local Mac installation and first result; a remote web client,
Linux emulation or an unsigned skeleton does not satisfy it. Preserve the Docker
control plane, native user Runner and Task → Run → Events → Artifacts lifecycle.

## Current code and verified upstream constraints

`scripts/desktop.py` retains the Linux-only consumer prerequisite gate. Independent
Darwin kernel ownership, peer credentials, telemetry, native Python and installed
Runner components have passed the platform checks below. Consumer .app packaging,
the Docker Desktop bridge and model setup/catalog are still separate requirements.
Removing the launcher's platform check alone cannot produce a correct Mac package.

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

Mac desktop storage uses `~/Library/Application Support/AI Station` for retained
code, configuration and data. A separate short private directory under
`/private/tmp`, named from OS UID and the canonical desktop-root hash, owns the
lifecycle socket. Its private single-link marker binds the full root hash/UID;
unrecognized contents, links, unsafe modes or a conflicting marker are refused.
The Runner socket lives in a separate `runner` child, so its container mount
cannot expose desktop Stop/readiness authority. Existing Linux XDG paths and
control addresses remain unchanged. These storage primitives do not remove the
Linux-only consumer prerequisite/GUI guard.

Native presentation uses one small AppKit program and a bounded Python stdin
protocol. Dialogs, an indeterminate preparation panel and status choices reuse
the existing desktop supervisor. The application entry retains an NSApplication
delegate for Dock reopen/Quit; it starts only the bundled Python/script and
reopens a retained version when available. Quit signals only its owned NSTask
child; the Python supervisor performs workload shutdown. Presentation receives
neither provider credentials nor private browser/setup URLs. The CLI
`--package-check` verifies package files without creating station data or starting
workloads. Native compilation/window and long-path control experiments remain
component qualification, not complete consumer acceptance.
[AppKit termination contract](https://developer.apple.com/documentation/appkit/nsapplicationdelegate/applicationshouldterminate(_:)?language=objc),
[indeterminate progress](https://developer.apple.com/documentation/appkit/nsprogressindicator/isindeterminate).

`scripts/macos_application_python.py` builds the application interpreter from the
qualified dependency layer. It installs a regular pure-Python Host Runner wheel,
built only from tracked source, into a separate copy without developer PYTHONPATH
or mutation of the verified base layer. A separate application receipt covers
source, wheel and final files, while checking the entire unchanged original
inventory and exact installed Runner bytes. Wheel construction uses the normal
project build backend in a minimal developer environment; target installation is
offline and hash-pinned, with no dependency resolution or target Mac execution.
Dirty input requires an explicit private-qualification flag and remains marked.
Native acceptance must then use this interpreter's isolated
`-m ai_station_runner.main`, without repository-source path injection. This is
package preparation, not permission to bypass the transport/consumer gates below.

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
   and `hw.memsize`/`vm.swapusage`. Available RAM estimates free plus inactive
   pages from one VM snapshot, following the
   [psutil macOS method](https://github.com/giampaolo/psutil/blob/master/psutil/arch/osx/mem.c).
   The disjoint queues and estimate basis are reported separately. Speculative
   pages are already included in free; purgeable/compressed counts are not added.
   Used RAM here means total minus that available estimate, rather than psutil's
   active-plus-wired definition. Impossible sums and failed observations stay
   unknown. Inactive pages are reclaimable estimates, not guaranteed allocations.
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

The first complete [actual native run](https://github.com/jahu/ai-station/actions/runs/41343995954)
passed at reviewed source `47430a0f575310819a48dee81d38e68cdb3bbb05` on
macOS 15.8.2 ARM64 and macOS 15.7.9 Intel. Each complete native-family cohort
passed 147 cases with one skip. The explicit native ownership/deadline/recovery,
kernel identity, RAM/CPU and Metal-observation gates ran against the Mac APIs.
Both actually assembled and executed pinned CPython 3.12.14; native dependencies,
source Runner import, the 160-sample PCM FFmpeg round trip and unchanged complete
layer inventory passed. This does not qualify model/Metal inference, Docker
Desktop transport, the declared minimum OS versions, signing or consumer setup.
The initial setup failures remain recorded: the old developer lock lacked hashes,
and optional Linux media QA required an unavailable Intel ONNX Runtime wheel.
The final native check graph retains the shared pinned versions and all four
native test families; no tested contract or failure was waived.

`operation=macos-native-inference` is a separate explicit owner/public-only opt-in.
It retains the same free standard hosts, native tests, permission/time bounds and
package-import gates, then downloads only the matching pinned llama.cpp SDK and
the official [Qwen3 0.6B GGUF](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/23749fefcc72300e3a2ad315e1317431b06b590a)
Q8 fixture (639,446,688 bytes, exact LFS SHA in `packaging/macos/inference-fixture.json`).
Ordinary `macos-native-checks` still downloads/runs no real model. The fixture is
not an operational model recommendation, a coding-context profile or a change to
the workstation's configured models. Its 512-token CPU context exercises the
actual native load/stream/observer-replacement/owned-Stop path within hosted RAM;
normal GGUF geometry and conservative live RAM admission remain mandatory.
Insufficient RAM fails instead of forcing an allocation or relaxing the policy.

The helper claims new private fixture storage, uses the existing exact-size/hash
input fetch and native inference probe, and exports only controlled status,
memory counts and response lengths/hashes. Failed/uncertain state is retained;
existing fixtures are never adopted/replayed. No operator assets, model files,
credentials or prompts from this workstation are sent to GitHub. Whole consumer
installation, Docker Desktop/Metal inference and cross-process restart remain
separate gates even when this developer CPU fixture passes. Record actual results
before claiming successful model execution.

The first explicit two-architecture CPU fixture run (41345738478) failed, and
is not inference acceptance. ARM exposed the earlier free-only RAM admission
error; Intel failed native startup after input verification. Follow-up changes
estimate free plus inactive pages, enforce the child socket umask, and retain
only fixed native status/error/exit metadata on failed startup. Neither the RAM
budget nor private-socket validation is bypassed to obtain a passing test.

The corrected [actual CPU inference run](https://github.com/jahu/ai-station/actions/runs/41347047301)
passed on both architectures at `f5095590971bc83781d3c3a9aff274bcc012c0e7`.
Each native kernel/observation cohort passed 149 cases with one skip; bundled
CPython/native imports and audio checks also passed. The fixed verified Qwen
fixture loaded with its inspected 1756 MiB admission budget and 512-token context,
completed two bounded SSE replies across observer replacement with the same
process, then confirmed owned Stop and private socket cleanup on both hosts.
ARM observed 3112.8 MiB available (84.7 free + 3028.1 inactive, rounded); Intel
observed 9630.2 MiB available. Neither forced allocation nor a socket-policy waiver
was needed. Normal checks passed 456 cases across 18 affected families, with eight
opt-in skips, plus whole Python lint/format. This qualifies the native CPU fixture
only: complete cross-process/station restart, Metal inference, Docker Desktop
bridge, consumer installation/minimum OS and signing remain unqualified.

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
Q8 KV/state geometry and 1 GiB headroom. It compares the current free-plus-inactive
RAM estimate and retains other live/uncertain reservations; this deliberately
double-counts already allocated resident memory rather than promising aggressive
packing.
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
inherits only fixed per-instance environment/cache paths. The process launches
with child-only umask 077, including when its parent uses a public umask, so the
inference socket is private at creation without a later permission-repair window.
Its stdout/stderr are discarded at process creation, preventing another user's
prompt or response from
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
identities, and never raw upstream errors. The default in-process probe retains
`cross_process_restart_tested=false`; only successful explicit process recovery
can change it. Every native-model pass still records
`macos_installer_qualified=false` and `other_os_user_tested=false`. It does not qualify Docker Desktop transport,
a complete station/process restart, GUI installation, updates or Gatekeeper.
`--cross-process-recovery` adds a separately isolated native owner process. It
receives only a private frozen fixture request, starts the verified model and
writes a bounded private handoff with its PID, model PID, instance and response
hash. That process must exit successfully and be reaped before a new manager
attaches the exact original model PID and streams the second reply. The helper
uses isolated Python, a minimal fixture-only environment and private umask; raw
stdout/stderr are discarded. A timeout signals only its immediate owned helper;
the original run's durable native Stop still governs the separate model. Failed
handoffs retain proof and never count as successful recovery. The explicit CI
inference operation now requests this mode; normal checks run no real model.
Only a completed native run can qualify that cross-process model recovery. It
still does not qualify a whole station restart, consumer installer or bridge.

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
child is only a negative-platform control. The owner-dispatched native run above
qualifies observation on its two actual Mac hosts, not Metal inference or other
hardware/OS versions.

The native process candidate extends the existing ProcessManager through narrow
boot/capture/liveness/launch hooks; it reuses the same journal, idempotency,
deadline, cancellation and recovery implementation. Normal Runner construction
now selects the Darwin adapter on macOS, the unchanged Linux manager on Linux,
and refuses unsupported platforms before creating storage/recovery timers.
The FastAPI application's global operation dependency restricts Darwin to health,
read-only hardware, owned-process inspection and Stop. It matches method and
registered route template, not URL prefixes or caller-supplied platform fields;
included/future adapters remain unavailable by default. Native model setup,
inference API routing, CUDA/media and the consumer launcher are not activated.
The Linux-only userspace-tailnet service is not restored at Mac startup.

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
The earlier owner-dispatched Mac Stop/deadline/recovery results qualify these
ownership primitives. The new normal-Runner integration adds both simulated
platform-policy tests and an explicitly opted-in native private-UDS experiment:
start the actual runner main, reject a second owner, inspect/recover the same
owned process, refuse unknown IDs, Stop only that group and remove the socket on
normal shutdown. The Linux control also runs in ordinary validation. Record actual
Mac integration results separately; memory policy, Metal, Docker Desktop and the
complete consumer launcher remain independent gates.

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

The first actual [cross-process model recovery run](https://github.com/jahu/ai-station/actions/runs/41348077079)
passed at `8981f2176623185e9c87ea5e780a9a3db9c00a72` on ARM macOS 15.8.2
and Intel macOS 15.7.9. Both confirmed original-owner process exit, reattached the
same live model PID, completed the second SSE reply, and confirmed owned Stop and
private socket cleanup. Response lengths/hashes matched across recovery on each
host. Native kernel/import/audio gates also passed. Normal validation passed
250 cases across nine complete affected families, with six opt-in skips, plus
whole Python lint/format. This qualifies the developer model-owner lifecycle,
not a full station restart, Docker Desktop bridge, Metal inference, GUI installer,
minimum OS or signing. The complete NR-13/14 consumer gates remain open.

### Bundled interpreter model gate

Earlier actual native inference/recovery runs used the developer interpreter;
the pinned CPython 3.12.14 package passed separate native-import/audio gates.
The explicit inference workflow now executes `macos_package_import_probe.py`
under the exact bundled interpreter with `-IB` and the architecture plus
`--run-native-inference`. It first checks the complete pinned Python inventory,
imports and native audio, then uses the existing fixed CPU fixture and isolated
owner-process recovery. Both native owners use that same bundled interpreter.
A complete model/recovery/Stop result is required, and the shipped inventory is
checked again after inference. No developer/user Python site or PYTHONPATH can
supply missing package dependencies. Ordinary native checks retain their no-model
path. This closes a package/runtime integration gap; it does not add or enable a
consumer launcher, full station restart, Docker bridge, Metal or signing.

The first bundled-interpreter run41349185644 failed its final unchanged-inventory
gate on both architectures, despite successful model replies/recovery/Stop.
A regression reproduced interpreter-cache writes by the native exec barrier in
an isolated temporary bytecode prefix. The Darwin barrier now also uses `-B`,
preventing those writes instead of accepting new files or rewriting the receipt.
Failure reports include only added-bytecode/other-file counts, not file paths or
contents. This fixes the candidate launch path only; Linux launch is unchanged.

The next actual run41349651754 retained the same failure gate after fixing the
exec barrier. Its safe report showed 45 added bytecode files on Intel and 42
on ARM, with three modified files on ARM and no other added files. The read-only
Metal observer was a second child missing `-B`.
A separate temporary-prefix regression failed before that fix as well. Both
fixed native children now prohibit bytecode writes. No cache file is accepted
into the receipt and no unrelated runtime or Linux launcher changes.

The corrected [actual bundled-runtime run](https://github.com/jahu/ai-station/actions/runs/41350101602)
passed at `79425827f43c36273d24415563bceb614ad37004` on ARM macOS15.8.2
and Intel macOS15.7.9. Both used exact isolated CPython3.12.14 for imports/audio,
model startup and the separate model-owner process. CPU replies, owner exit,
same-model-PID recovery, owned Stop and socket cleanup passed, followed by an
unchanged full Python file inventory. Each native kernel/observation cohort
passed151 cases with one skip. Local validation passed313 cases/13 complete
families with five opt-in skips, then the final complete Metal family40/one skip
after a test-fixture refinement; other checked source stayed unchanged. Whole
Python lint/format passed983 files. This closes the bundled-interpreter inference
and immutability gap, not consumer GUI/bridge/Metal/station restart/minOS/signing.

### Control-plane image production

Apple Silicon needs the actual `linux/arm64` application image alongside native
Darwin Python; an amd64-only Linux package is not a Mac ARM bundle. The trusted
developer helper `scripts/build_control_plane_image.py` reuses the canonical
Dockerfile and changes only its frontend stage to BuildKit's native
`$BUILDPLATFORM`. JavaScript assets are architecture independent; backend Python,
native wheels and the final image still target the explicitly selected platform.
The ordinary Dockerfile, legacy/local build and end-user startup stay unchanged.
This avoids spending the entire Node install/typecheck/build under emulation.

Use an existing local Buildx builder (ordinary developer Docker authority):

```sh
python scripts/build_control_plane_image.py --platform linux/arm64   --builder <local-builder-name> --tag ai-station:<new-package-tag>   --output /absolute/new/package-image-proof
```

An optional `--buildx` selects an already verified standalone developer tool.
The helper refuses dirty source, existing tags, uncertain image absence and
existing proof directories. It freezes the source head and both Dockerfile hashes,
loads locally without pushing, and verifies target OS/architecture, non-root user
and the Buildx image digest before publishing an image-only receipt. Interrupted
or inconsistent output remains for inspection. It changes no daemon, OS/emulator,
GPU configuration or running application and does not grant a Runner/agent API.

Actual API/worker/first-admin/restart qualification is separate from image
production. Userspace-emulated ARM checks on Linux do not qualify Docker Desktop
socket sharing or the complete Mac consumer journey. Package the verified target
image only after those platform and application gates are satisfied.

The producer was actually exercised at `c20560373c176bd9bc21947f9ef00384f0da6d9a`:
local `linux/arm64` and `linux/amd64` images built and passed target/digest/non-root
inspection. The ARM image `sha256:01418ede41ab3337df8d854d29f2b786793390e533c323a0edf939ebc875e487`
then ran under project-owned userspace QEMU on Linux, with unchanged host binfmt.
Its real API created the first administrator, served compiled UI, executed an
ordinary fake Run through the separate production worker/spawn path, streamed
SSE and observed the separate scheduler heartbeat. Restarting only that owned API
retained its cookie/account and completed Run. All three private test containers
were stopped/removed afterward; production was untouched and no real AI model ran.
This qualifies the ARM image/application fixture, not a Mac installation or bridge.

The first fixture's console read exceeded a 30-second QA observation budget.
That failed result was retained; all old containers were confirmed absent and the
unactivated first-admin database passed integrity/schema inspection. A separate
fresh fixture with a bounded 120-second console budget completed the full journey;
its actual console read took 28.5 seconds under emulation. No product timeout or
failed assertion was waived. The superseded all-emulated frontend comparison was
intentionally canceled after the native-frontend ARM candidate had built; it is
not a successful baseline image claim. Its locked `npm ci` took 842.7 seconds versus
40.6 seconds natively, one local build observation rather than an AI speed promise.

Validation: 58 cases across three complete package families, whole Python
lint/format of 985 files, production/development Compose validation, both actual target
image builds and the scoped ARM API/worker qualification above. Evidence remains
in the private `arm64-control-plane-20261101` acceptance directory. Full consumer
Mac app/launcher, Docker Desktop transport, Metal, station restart/update/removal,
minimum OS and signing remain independent NR-13/14 gates.

### Normal Host Runner integration

Owner-dispatched run
[`41355906536`](https://github.com/jahu/ai-station/actions/runs/41355906536)
passed at implementation head `9e0b9c38a4ef7ea9e92737b755052f00ea21dfe9`:
243 passed/one skipped on each actual ARM macOS 15.8.2 and Intel macOS 15.7.9.
Alongside the existing kernel/observation families, the normal Runner experiment
started its real main over a mode-0600 Unix socket in a mode-0700 directory,
rejected a second owner, recovered an existing owned process, rejected unknown
IDs and stopped only that group while an unrelated process survived. Normal
shutdown removed the socket. Every unqualified registered route, a later included
route and caller-supplied platform overrides were denied on Mac. Separate shipped
Python 3.12.14 imports/audio and unchanged-inventory checks also passed on both
architectures; normal Runner main used the native check interpreter. This was
the no-model operation, not a repetition of the earlier native inference fixture.

Review also found two cross-platform API issues. Generic process inspection/Stop
could delegate a Linux image-container journal on Mac, and uncertain kernel facts
could escape as raw API failures. Six regressions failed before the fixes; generic
Mac process operations now use only native ownership and return a fixed
inspection-required conflict for incomplete facts. No unverified signal or Linux
container operation is authorized by that response.

Equivalent local validation used `scripts/check.sh` with all complete Host Runner
families and affected API/package families: 2288 passed/eight skipped, plus whole
Python lint/format of 987 files. The initial broader run was deliberately
interrupted in favor of these complete affected families and is not counted as
successful; the prior full baseline remains separate evidence. No UI, deployment
or model files changed. Evidence is retained in private acceptance directory
`native-runner-platform-20261101`. Consumer launcher, model API routing, Docker
Desktop, Metal, complete station restart/update/removal and signing remain open.

### Installed application Python preparation

The application-layer producer passed 97 cases across six complete package
families plus whole Python lint/format of 989 files. Tests cover source
cleanliness, ignored/private-file exclusion, symlink escapes, package-byte
substitution, dependency replacement, unexpected wheel files and recursive output
inside the base layer. It accepts uv's exact one-byte `.gitignore` output marker;
the first real attempt refused that harmless extra file, and that failure remains
recorded rather than counted as success.

Actual private ARM/Intel application layers were assembled on Linux using the
previously verified native dependencies. Each contains all 210 tracked Runner
package files with matching bytes; their final inventories contain 3902/3903
files respectively, with every base file unchanged. Both receipts deliberately
record `source_dirty=true` and `native_application_executed=false`: these are
private preparation fixtures, not release artifacts or native consumer acceptance.
No Mac code, real model, container or production process ran in this assembly.
Evidence is retained in `macos-application-python-20261101`; next qualify the
installed module/normal Runner under the exact isolated native interpreter before
the consumer launcher and transport gates.

Installed-module qualification must verify the full application/base inventories
and tracked Runner bytes before importing it, and require the exact isolated
Python 3.12.14 architecture. The probe adds no repository directory to sys.path:
both imports and `-IB -m ai_station_runner.main` must resolve the installed wheel.
Use only fresh private fixture data and fixed sleeping children to check UDS
permissions, duplicate-owner refusal, recovered identity and scoped Stop. Preserve
an uncertain ownership fixture instead of deleting its journal; compare the full
application inventory again after execution. No model, Docker Desktop or consumer
readiness follows from this bounded developer experiment.

The installed-package experiment uses a separate fixed fixture-owner mode. It
accepts only a fresh private `/private/tmp/ais-app-*` directory and canonical UUID,
launches one fixed sleeping child with minimal environment, publishes a bounded
handoff and exits normally. The original helper must be reaped with matching PID
and successful exit before normal Runner main starts. This checks real owner
loss without leaving the original manager/reaper as a concurrent journal writer.
Unknown ownership retains the private fixture; helper cleanup signals only its
own immediate child, while managed cleanup uses the native ownership journal.

Actual owner-dispatched run
[`41359243590`](https://github.com/jahu/ai-station/actions/runs/41359243590)
passed this installed-package contract at implementation head
`47cd414b349b2ec4f57f28f96f2ea85d2b472621` on ARM macOS 15.8.2 and Intel macOS
15.7.9. Both used the exact bundled Python 3.12.14, a regular installed Runner
wheel, no repository sys.path injection and normal `-IB -m ai_station_runner.main`.
The original owner helper actually exited and was reaped before same-process-ID
recovery; private UDS, duplicate/unknown-owner refusal, scoped Stop, survival of an
unrelated process, normal socket cleanup and unchanged complete application
inventory all passed. Existing native kernel/observation families passed 243 cases
with one skip on each architecture; base Python imports/audio remained unchanged.

Local validation passed 118 cases across seven complete package families and
whole Python lint/format of 991 files. The installed package now requires exact
tracked file-set equality as well as matching bytes; an added untracked module is
rejected. An initial new unit test incorrectly expected an entirely empty pytest
directory despite the backend's existing data fixture; it was corrected to assert
no additional files, and the complete selected validation then passed. No failure
was waived. Evidence remains in `macos-installed-runner-20261101`. This no-model
experiment qualifies the installed native Runner component; the .app/launcher,
native model API/catalog, Docker Desktop transport, Metal, whole-station preserving
update/removal, minimum OS and signing remain full NR-13/14 acceptance gates.
