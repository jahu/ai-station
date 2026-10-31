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
