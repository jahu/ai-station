# Windows consumer installation — NR-13/14

The full [0.1.0 requirements](next-release-0.1.md) remain authoritative.
Windows is not yet qualified or advertised as supported. Linux/Ubuntu acceptance
cannot establish Windows networking, lifecycle, GPU or security behavior.

## Chosen boundary

Use a private, application-owned WSL2 distribution with its own Docker Engine,
Linux user-level Runner, private Unix sockets and existing compiled application.
Do not adopt a user's Ubuntu, Docker Desktop, default distribution or filesystem.
Do not pass a Docker socket, raw shell or Windows process access into the API.
The Windows shell owns only distribution installation and desktop lifecycle;
workloads still use the existing Task → Run → Events → Artifacts path.

Build an immutable guest filesystem from a digest-pinned official Ubuntu image
and a checked clean-source Linux package. Install the OS dependencies during the
package build, not from a generated user/model script. Create one ordinary
`station` account, disclose its guest-local Docker authority, enable systemd and
the guest's Docker service, and disable drive automounts and Windows executable
interop for this distribution. Keep data in its private ext4 filesystem. The
WSL kernel/Windows device namespace is still shared infrastructure; these settings
do not claim a hostile-user VM security boundary.

WSL installation/virtualization, updates or reboot can require Windows OS consent.
Offer the documented OS action; never enable features, reboot or modify global
`.wslconfig`, default distro, firewall, GPU drivers or another distro silently.
CPU is the first proposed model profile. GPU support remains a distinct actual
WSL/NVIDIA/container-runtime qualification, with no automatic driver installation.

Microsoft documents [per-distribution versus global settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config),
[scoped import/terminate commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)
and [Windows-to-WSL localhost forwarding](https://learn.microsoft.com/en-us/windows/wsl/networking).
Those are platform contracts to test, not evidence that this application works.

## Implementation sequence

1. Build/hash/audit a private guest filesystem without starting nested daemons or
   mounting host paths. Include the pinned compiled image and bundled Python;
   carry provenance and dependency licenses. A fixed guest desktop bridge accepts
   only start/status/open/stop, executes the ordinary user launcher and transports
   the validated first-admin browser link through an inherited private pipe.
2. Add a native Windows onboarding/status shell. Per-user ACL-protected state
   contains a random distro identity and version receipts. Validate System32
   `wsl.exe`, registered ownership/WSL2 version and immutable archive hash before
   any operation. Import only into a fresh app-owned folder. Interrupted setup
   reconciles its recorded identity; a name collision never adopts existing data.
3. Windows opens only the validated guest readiness URL after a successful
   Windows-side loopback probe; no IP fallback, port proxy, firewall change or
   LAN listener. Never write setup authority to logs, command arguments or
   shortcuts. Closing the UI keeps owned generation alive; Stop uses the guest's
   instance-bound existing lifecycle channel, never `wsl --shutdown`.
4. Install updates into a retained package version inside the owned distro,
   after source/hash validation. Existing work keeps running until explicit idle
   restart. Uninstall removes entry/code only; deleting user data/distro requires
   a separate destructive action and backup option. No automatic unregister.
5. Real Windows 11 x64 clean-machine acceptance: missing/ready WSL, OS consent
   cancellation, import cancellation/recovery, first admin, actual CPU engine and
   weight download, Send/reply, reload, background/reopen/Stop, update and
   uninstall/reinstall retaining account/cookie/history/Library/memory/models.
   Exercise paths with spaces/Unicode, port collisions, stale/foreign distros,
   tampered packages, multiple Windows users and bounded CPU RAM/zero swap.
   Inspect actual sockets, mounts, app UID, process ownership and network exposure.

Normal tests must not import a distro, install WSL or alter the development host.
Linux guest build and simulated command tests are evidence only for those layers.
Signing, native UI/accessibility and genuine WSL first-result gates remain open
until exercised on the advertised OS. Keep test images ephemeral after compact
proofs are retained, following the owner's disk-cleanup instruction.

## Implemented guest layer — 2026-10-31

`scripts/build_windows_guest.py` consumes an explicitly hash-checked amd64 Debian
package and a clean source checkout. It builds from the pinned official Ubuntu
24.04 image, installs the guest OS dependencies without starting daemons, exports
only its own never-started container, and publishes a compressed filesystem plus
source/package/image/archive identity receipt. It refuses existing destinations
and removes incomplete output after export failure. This is a developer builder,
not the finished Windows installer UI.

The actual guest image was built with the bundled compiled application/Python.
Isolated no-network, no-host-mount container probes used that exact image:
ordinary `station` account status passed; root, another account and extra command
arguments were rejected. Installed systemd/Docker enablement, private home,
empty machine identity and disabled drive/interop configuration were checked.
No nested Docker daemon was started. These probes qualify installed guest bytes
and fixed operations only; they do not qualify WSL boot, Windows networking,
background lifecycle, resource scopes or a Windows first model result.

The complete affected desktop/package/access scope passes 134 tests and the
whole Python lint/format gate. The QA catalog is version 34 with planned Windows
cases SETUP-149–152; all operator answers remain untested. Offline QA tools pass
26 tests. The native Windows shell, owned registration/import/recovery, actual
platform acceptance and signing remain required next steps. Private build/layer
proofs are in `data/acceptance/windows-consumer-install-20261031/`.

## Windows ownership state increment

The native shell uses a pure PowerShell state/command module before wiring OS
operations. A random installation UUID fixes the private distribution name,
local directory, accepted package hash, phase and later registry identity.
Reconciliation compares both registration name and canonical private path,
requires WSL2, and verifies the guest build receipt before marking readiness.
A missing previously registered distro, reused name, foreign folder, duplicate
registration or changed registry ID requires inspection instead of adoption.
An unregistered leftover disk is preserved for recovery rather than overwritten.
Only start/status/open/stop can produce fixed ordinary-user bridge arguments;
there is no shell, global shutdown, terminate or unregister plan.

This module alone is not an installer. Windows ACL/reparse validation, immutable
archive transfer, registry/WSL execution, native UI and actual WSL acceptance
must still be implemented/tested before exposing a consumer installation flow.

## Private import controller — implementation in progress

`InstallFiles.psm1` holds an exclusive installation lease, writes bounded strict
UTF-8 state through a flushed atomic replacement, and verifies archive size/SHA
while retaining its read handle for the import. The real portable .NET file
checks found and fixed PowerShell's empty-string conversion for a null backup
argument. Mandatory Windows sharing/deletion semantics remain a Windows gate;
Linux file tests do not establish them.

`PrivateStore.psm1` limits storage to the current user's LocalAppData leaf, creates
an owner/SYSTEM-only protected ACL, rejects junction/reparse paths and unsafe
existing ownership/access, and refuses unmarked existing data. It does not
repair parent/profile permissions. `Setup.psm1` snapshots the accepted manifest
and state atomically, probes Windows prerequisites with stdin closed, imports
only the recorded private distro, and verifies both the registration identity
and exact guest source receipt before advancing readiness. Windows environment
forwarding is cleared. A lost/unknown import is inspected instead of repeated;
existing disks and replaced/foreign registrations are preserved. Desktop start
returns its private process pipe; status/open/stop retain fixed guest operations.
These Windows-specific APIs have not yet been exercised on Windows.

The portable checks passed 33 ownership assertions, three non-Windows guard
refusals, 15 real .NET file assertions and 20 manifest/imported-source assertions,
including language-independent source comparison. Browser binding is separately
qualified in [desktop installation](desktop-installation.md#bind-browser-readiness-to-the-running-station).
The compiled accounts API and real PowerShell HTTP probe passed without sending
bootstrap authority in HTTP or logs. This does not qualify Windows native UI.

Next: native onboarding/status/background controls; automatic Windows-side port
selection with a typed guest handoff; preserved updates/removal; and clean
Windows first-result acceptance. Account for the physical Windows volume's
remaining capacity rather than advertising the WSL VHD's virtual maximum as free
model storage. Package the reviewed current browser-identity protocol together;
the earlier private guest archive is a historical fixture, not the new UI's
qualified payload. Signing and macOS/full catalog/quality requirements remain
part of the original release scope.
