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
