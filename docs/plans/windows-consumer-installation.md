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

This module alone is not an installer. Private ACL/archive/import and native UI
implementations are described below. Actual WSL execution, preserving updates
and the complete first-result journey remain required before publishing a
consumer installation flow.

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
Ordinary-user NTFS/file contracts and package/UI construction now have actual Windows coverage described below. Imported WSL guest boot, workload execution and preserving guest updates remain separate gates.

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

## Native shell and protocol 2 — private candidate

The WinForms shell now implements preparation, Start/Open/Stop, status, tray and
single-window controls. Import runs in a background PowerShell runspace. Closing
its window keeps the owner alive; Stop and exit waits for a confirmed shutdown.
An owner-only lifetime file spans Windows sessions and fences uninstallation.
The Inno definition retains host versions separately and preserves guest data.
These are implemented sources, **not a Windows-qualified or published installer**.
Guest-version update still deliberately refuses a different package; its reviewed
preserving update flow, physical host-volume admission, native accessibility,
signing and all genuine Windows acceptance remain required.

Windows selects a free loopback port in 8765–8864. The bounded ordinary-user
bridge passes it to the owned launcher's child environment without changing
saved configuration. Protocol 2 is declared in Debian metadata and both guest
receipts; legacy guests are rejected before use. If the desktop owner is gone
but the actual launcher lock is held, status/Stop report inspection required
rather than falsely claiming shutdown or signaling an unverified process.

Verification at source `31af665` passes 182 complete affected Python cases and
whole-source lint/format (942 files). The real exported protocol-2 archive was
audited across 29,023 entries, 5,935 package files and 1,048 package links.
Exact-image offline/no-host-mount probes verify ordinary-user protocol/status
and root/foreign-account rejection. Portable PowerShell checks include 38
ownership, 15 file, 20 manifest, 16 browser and three platform-guard assertions,
plus real occupied-port selection. Review reproduced and fixed a background
result bug: accessing `.BaseObject` directly lost native process/string results.
Six actual runspace regression cases cover object/string/process preservation
and rejection of errors, null or multiple results. None of these checks claims
NTFS ACL/mandatory sharing, WSL boot or rendered Windows UI qualification.

Publisher packaging requires a clean identified checkout before and after
staging, snapshots the validated guest manifest, and hashes the staged host
payload. Keep only the current private guest/archive and compact evidence after
audit; remove superseded build trees/images without touching production or its
models. The full NR-01–NR-14 goal, including macOS, remains open.

### Native qualification in progress

Use a disposable Microsoft Enterprise evaluation VM with a verified publisher
ISO, UEFI/vTPM and an ordinary limited user token. Keep host drivers, Docker
services, filesystems and production unchanged. Private test transport is bound
only to loopback with a random capability, and VM operations check the exact
recorded process/start identity. Delete its large disk/media after qualification
and retain compact provenance, screenshots and results. This is evaluation
infrastructure, not an application feature or a public Windows support claim.

The publisher requires Inno Setup 7. Explicit x64 setup/install mode prevents
uninstall checks from selecting WOW64 PowerShell while the native runtime
requires x64 Windows. The build must reject ARM64 until separately qualified.
See the publisher's [architecture documentation](https://jrsoftware.org/ishelp/topic_setup_setuparchitecture.htm).

Preparation has a Cancel setup action using an in-process cancellation token.
The UI remains responsive while stdout/stderr drain concurrently. Cancellation
stops only the exact launched WSL client process handle, never a distribution or
another process. A request canceled before launch returns to its reserved state;
after an import has been dispatched, its receipt remains for reconciliation
because WSL's service may finish independently. A canceled or failed operation
never triggers application startup. Stop and exit can cancel preparation and
wait for that safe boundary. Seven real portable process/runspace cases prove
output/error bounds, cancellation delivery, own-client exit and preservation of
an unrelated process. Genuine WSL cancellation/recovery remains a native gate.


## Actual Windows qualification — private evaluation, 2026-11-01

An owned Windows 11 x64 evaluation VM (build 26300) now runs the actual built-in
PowerShell 5.1.26100.9444 with a limited, non-elevated user token. Its official
Microsoft ISO matches the publisher's published SHA-256. UEFI/vTPM and nested
virtualization use project-local tools; no host OS, driver, GPU passthrough or
host filesystem mounts were changed. Evaluation media is never redistributed.

The native checks pass 38 ownership, 15 file/hash/sharing, 20 manifest, six
runspace and 15 browser-protocol assertions, plus actual occupied-port selection.
Five further real Windows cases verify private/public ACL rejection and existing
and dangling junction boundaries. Seven real process/runspace cases verify
cancellation, bounded replies and preservation of another process. Tests remain
separate from the operator QA workbook; no operator answers were prefilled.

Actual native compilation exposed PowerShell 5.1 parameter conflicts and the
Add-Type name cache. The publisher now uses a non-loading CodeDOM compiler,
checks the emitted PE as x64/GUI, deletes its compiler temporary files and emits
only to fresh payload/installer folders. Repeated same-session native Inno 7.1.1
builds pass. Keeping the already compressed guest archive uncompressed in the
outer installer reduced measured compiler time from 88.031 to 8.422 seconds in
this test VM; it does not change guest bytes or remove checksum verification.

The actual per-user installer exits successfully without elevation, creates its
Start menu shortcut and opens its installed native controls. The startup screen
has one primary setup action. Interactive cancellation returns to a resumable
screen. Both application-consent denial and Windows UAC denial preserve an empty
registration inventory and create neither a guest folder nor an import receipt.
The confirmed x64 GUI executable and real screenshots are private evidence under
`data/acceptance/windows-native-qualification-20261031/`.

The actual Microsoft WSL installer requires a Windows restart. WSL 3.0.3 even
returned exit code zero from `--status` while explicitly reporting unavailable
virtualization before that restart. Initial preparation now rejects a pending
system restart **before** reserving/importing a guest, with a typed restart reason
for the native UI. Existing node status/open/stop remain usable during a pending
Windows update. Controls allow ordinary OS shutdown/logoff rather than hiding
and canceling Windows shutdown. Native prereq restart, imported guest startup,
first actual CPU reply, resource accounting, recovery, preserving guest update,
removal/reinstall, native accessibility/DPI and signing remain open acceptance
gates. No public Windows installer or Windows support claim is added.

The full original NR-01–NR-14 release scope, including macOS, broader hardware
and model profiles, media quality, naming and final operator QA, is unchanged.

After the real prerequisite reboot, the pending-restart key clears and the
installed controls reopen without elevation. Exact launcher reproduction found
another native incompatibility: WSL 3 treats quoted option tokens such as
`"--version"` as a default-distribution invocation, while bare `--version` works.
The private serializer now leaves fixed switches bare and quotes only
whitespace-bearing data. Actual same-CWD/environment probes pass both options;
twelve process/argument/cancellation cases pass on Windows. Five successive
native installer builds now pass, including the corrected adapter. The existing
VM and import state are inspected rather than restarting on observation timeout.

The corrected installed launcher has now imported its own WSL2 distribution,
verified the registered path and guest receipt, and started the existing API,
worker, scheduler and search services. Windows-side loopback health and the
private desktop's ready/background status both pass. A separate ordinary Edge
profile used the private first-admin link and submitted the actual account form;
the new administrator remained authenticated while opening guided model setup.
Scoped Stop then confirmed that the desktop owner had exited before the test
machine shut down normally. These checks still do not establish model inference.

The first 12-GiB Windows fixture exposed an important hardware boundary: WSL's
unchanged default memory allocation was about 5.77 GiB. The 4B CPU recommendation
correctly refused its 4069-MiB model budget plus 2048-MiB system headroom. The same
installed test disk is being qualified on a 16-GiB Windows fixture; neither the
application's memory thresholds nor global `.wslconfig` are changed to pass it.
Smaller starter models and clearer host-versus-guest memory guidance remain
consumer-catalog work, rather than silently claiming the 4B profile fits all
Windows machines. The completed OS installation ISO was ejected and removed
after boot/WSL verification, reclaiming 7.66 GiB while retaining the active guest,
current installer and compact proof. Remove the remaining disposable test disk
and obsolete publisher copies after final qualification.

### First real Windows CPU result completed

The same installed Windows fixture completed first-admin setup, fresh public
llama.cpp engine preparation, the verified 2,497,281,312-byte 4B Q4_K_M download,
the **Open Chat with this model** and **Send** controls, and a real
`WINDOWS_MODEL_OK` reply. Reload retained that exact assistant message and the
same authenticated account. The actual running Docker container had a
4,266,655,744-byte memory limit with the identical memory-plus-swap limit, no GPU
device requests, no network and no privileged mode. Its ordinary model Stop Run
then succeeded. This qualifies the exercised 16-GiB Windows / default WSL / CPU
profile, not GPU inference or every Windows memory configuration.

The current private native installer was exported from the guest and verified
as 438,049,757 bytes with SHA-256
`652ad15c9cd0add97a07f6b1bbc497b1d20df597d29ae8faddfb651b9cd589da`.
Evidence remains under the private qualification directory; screenshots and
evaluation media are not published. The installer is still an unsigned private
candidate, not a release asset. Full native accessibility/UIA/DPI/tray and
remove/reinstall acceptance, preserving guest updates, physical Windows-volume
admission, signing, macOS and the remaining original release scope stay open.

The real conversation also exposed unnecessary automatic web searching for a
literal-response instruction. That regression is tracked in
[web search](../web-search.md#contextual-search-necessity--observed-regression),
separately from successful native CPU inference.

## Preserving guest update — implementation contract

Update the application package in the existing owned WSL distribution. Do not
replace/import its root filesystem, unregister it, reset Windows features or
copy user data into a new installation. The native Windows installer is the
trusted caller; no application/agent/Runner HTTP action gains root or package
installation authority. The normal application continues to run as `station`.

The offline root helper (`packaging/windows/guest_update.py`) is an isolated
implementation layer connected to the private installer candidate, not yet
qualified or advertised as ready.
Its entry requires root **inside the exact named AIStation WSL guest**, not the
Linux development host. A bounded private input carries old/new immutable guest
identities and the verified package bytes, never commands, paths or URLs. Admit
only the same Ubuntu/Dockerfile/WSL/bridge recipe and a strictly newer AI Station
amd64 package with desktop protocol 2. OS/bridge recipe changes need their own
migration, rather than claiming that replacing the application updated the OS.

Hold the updater, desktop and launcher kernel locks before package replacement;
never signal an existing process or claim that an absent desktop window means
idle. Refuse nonterminal saved Runs. A private, integrity-checked pre-update
SQLite backup includes account/session/Library/memory history and retains its
original bytes on Resume. Stream/hash/length/metadata admission precedes the
fixed offline `dpkg --install`; verify the installed version and immutable
application manifest before replacing the guest identity receipt. A pending
journal binds the exact previous/target pair. Lost final acknowledgements inspect
the completed target and do not reinstall it; a different pending pair requires
inspection. Partial transfers are removed only if this operation created them;
existing files, backups, distributions and application data are never cleared.

The candidate now packages the same checked Debian file with the Windows
payload and binds its length/hash. A bounded native stdin transfer carries the
package without Windows-drive mounts. The Windows receipt advances only after
exact-target confirmation. Update is explicit; Finish work can start the old
version before an update begins, and pending-update inspection keeps status/Stop
while refusing a new start. Actual preserving updates, cancellation/lost-client
recovery and uninstall/reinstall on the retained Windows fixture remain required. Native
sharing/ACL, physical Windows-volume admission, accessibility and signing remain
separate acceptance gates. Normal tests use temporary databases and fake package
installation, never root installation on the workstation.

Candidate-layer verification: 213 cases in eight complete desktop/package/WSL
families passed; after the last pending-receipt review correction, all 46 updater
cases passed again. Whole-source Ruff/format covers 945 Python files. Real
`dpkg-deb` metadata/version comparison was exercised using synthetic packages;
installation itself used a fake `dpkg` and temporary private databases. Tests
cover original backup retention, active desktop/launcher/Run refusal, link and
permission boundaries, lost acknowledgement after the target receipt, matching
operation hashes with a different pending target, and owned process-group timeout
cleanup. A pending root marker blocks startup in the new desktop version while
retaining status/Stop. The Windows coordinator must still qualify admission from
an older installed launcher; these tests do not prove that platform transition.
Private evidence remains in `data/acceptance/windows-native-qualification-20261031/`.
This is not a Windows-qualified or published update flow.

Native binding verification adds 20 pure plan/refusal and real binary stdin
transport assertions plus 59 coordinator assertions with fake WSL. These cover
explicit Update, preserving registry identity, confirmation before Windows-state
publication, lost-acknowledgement reconciliation, previous-version work, pending
start refusal and status/Stop. The actual private Windows PS5.1 journey still
needs to qualify these sources; PowerShell7/Linux is not its substitute.

### Interpreter admission found by the actual image probe

The built WSL guest has no `/usr/bin/python3`; its Python is the already verified
application bundle. The initial native update candidate therefore could not run.
The fixed native plan now uses only that bundled interpreter or the private
frozen updater interpreter. A fixed read-only `/usr/bin/test` inspects pending
state and the known interpreter slot, so status/Stop do not acquire a system
Python dependency or package authority.

Before reading update input, the guest verifies the installed Python source/hash
inventory, copies it into its private updater directory, verifies and fsyncs that
copy, then atomically publishes it. The same process re-execs the original fixed
invocation there without consuming stdin. Later package replacement cannot
remove the updater's stdlib or libraries; Resume can use the same independent
interpreter even if the application package needs repair. A gzip-encoded fixed
source keeps the Windows argument vector below its checked limit; decoded input
is the publisher-verified program, never model/user code. No OS Python, driver,
Windows-host Python or online dependency install is added.

The actual exported image passed a no-network, read-only, bounded container probe:
6,773 interpreter files verified, the isolated interpreter executed its stdlib,
and repeated inspection reused that exact copy. This qualifies the package/SDK
layer only. Native Windows old-to-new data preservation and interrupted-update
qualification remain open. The `caf4717` complete normal Python gate passed
6,499 cases with nine explicit opt-in skips before this discovered integration
fix; later SDK changes require their affected tests and actual native checks.

The actual first offline-update attempt was stopped by Windows' pending-restart
preflight, before any package dispatch. The owned idle evaluation guest is
finishing its ordinary system update; no prerequisite registry marker is cleared
or bypassed. A native UI review found that an automatic status refresh could
replace the explicit restart instruction with “Update available”. The handler
now retains that instruction and clears Start readiness after a failed update
until a successful inspection restores it. This small state correction has a
parser check and review; its rendered Windows acceptance remains part of the
pending native UI gate.
