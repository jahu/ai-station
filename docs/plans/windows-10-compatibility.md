# Windows 10 compatibility

## Report and root cause (2026-11-08)

The published 0.3.1 installer rejects Windows 10 before application setup.
Inno Setup declares `MinVersion=10.0.22000`, and the native launcher independently
rejects builds below 22000. Both are Windows 11-only policy gates, rather than
an observed application dependency on Windows 11. Lowering only the installer
minimum would leave the second failure in place.

## Implementation and acceptance

Admit x64 Windows 10 21H2 / LTSC 2021 (build 19044), 22H2 (19045) and Windows 11.
Keep rejecting older Windows and non-x64 hosts. Use the existing private WSL2
guest, bundled Docker Engine, ordinary Linux Runner and loopback UI; Docker
Desktop and a host Python installation remain unnecessary. No global WSL
settings, foreign distributions, host drivers or firewall changes are allowed.

Microsoft supports WSL installation on Windows 10 build 19041 and newer;
[GPU compute](https://learn.microsoft.com/windows/wsl/tutorials/gpu-compute)
requires Windows 10 21H2 or newer. The minimum here follows the latter boundary.
[Systemd support](https://learn.microsoft.com/windows/wsl/systemd) requires WSL
0.67.6 or newer; the legacy inbox WSL can exist without supporting `--version`.
Detect the actual WSL version before creating/importing a guest and explain how
to install/update WSL through the existing explicit OS-consent path. Do not
silently enable features, restart Windows or reset another distribution.

Qualification must cover version/build/architecture boundaries, old/missing WSL
and actionable recovery, existing lifecycle/update/cancellation contracts,
installer compilation and actual Windows 10 install/launch/prepare/Start/Stop.
Reuse the checked Linux guest where application code has not changed. Record
native Windows 10 evidence independently of existing Windows 11 qualification;
simulated build numbers and Linux PowerShell do not establish native support.
Update the README, download page and setup guide with the precise Windows range
and prerequisites once verified. Do not replace existing published release
binaries or move tags: publish a new installer through the normal reviewed
release workflow. Master approval/merge stays exclusively with the human owner.

## Fresh Windows 10 observation and prerequisite repair

A real clean Windows 10 22H2 evaluation VM (19045) passed native PowerShell 5.1
contracts, built the installer with Inno and installed/launched the native UI.
Its original inbox WSL had neither `--version`, `--update` nor
`--no-distribution`; both virtualization features were absent. The old setup
command therefore could not prepare this OS. This is independent of the
Windows 11-only admission bug.

The existing explicit Windows-support action now launches a fixed elevated
installer helper. It reuses sufficiently recent WSL; otherwise it downloads
one exact Microsoft x64 WSL MSI, bounds its bytes, verifies SHA256 and a valid
Microsoft signature before any OS change. It enables only the two documented
WSL/Virtual Machine Platform prerequisites and installs that MSI without reboot.
The ordinary UI and a UAC prompt precede the helper. It never creates/adopts a
user distribution, changes the default distro/global WSL settings, touches GPU
drivers, or grants OS setup to application tools. Temporary downloaded inputs
are removed afterward; a requested Windows restart remains the user's action.
The modern WSL update action stays the trusted system launcher's fixed `--update`.
The real bootstrap qualification is recorded below.

The real bootstrap installed WSL 3.0.3 and both features, removed its temporary
MSI, and created no distributions. After reboot the old system launcher still
rejected `--version`, while the signed Microsoft launcher in Program Files
reported WSL 3.0.3 successfully on Windows 10 19045.2006. Native selection now
prefers that fixed Microsoft MSI location, validates the same signature/path
requirements and retains the system launcher fallback. PATH/user aliases are
never searched; an untrusted preferred executable fails closed. This also keeps
future preparation from unnecessarily reinstalling already modern MSI-based WSL.

Actual WSL `--status` then identified the base evaluation OS as too old:
`Wsl/WSL_E_OS_NOT_SUPPORTED` on 19045.2006. Microsoft's own diagnostic points to
[KB5020030 / revision 2311](https://aka.ms/store-wsl-kb-win10). Windows 10
21H2/22H2 therefore requires that cumulative update or a newer one. Read-only
preflight now checks the actual registry UBR before downloads/import and routes
the native UI to Windows Update. The bootstrap helper applies the same guard.
Windows 11 is unaffected. No arbitrary OS update is silently installed by AI
Station; the fresh owned Windows 10 qualification VM is updated separately.


## Actual Windows 10 qualification — 2026-11-08

The owned, isolated x64 Windows 10 22H2 VM was updated from 19045.2006 to
19045.2311 using the official Microsoft KB5020030 package, then restarted normally.
This was a test-fixture operation; AI Station does not install cumulative OS
updates. Neither the Ubuntu development workstation nor the retained Windows 11
fixture was changed. The VM had 8 GiB RAM, four virtual CPUs, no GPU passthrough
and no host filesystem mounts.

The final 0.3.2 installer and WSL payload were built from
`033fbfc5fd7a6d4e4fce5e4dd5c326fe37d3cbc8`. Native PowerShell 5.1 and Inno
compiled the installer; the installed native app imported only its own WSL guest,
started its bundled Docker control plane, worker, scheduler and user-level Runner,
and opened the actual browser UI. The following checks were executed:

- Real first administrator setup, browser login and compiled UI delivery.
- Actual Linux Runner hardware response from the CPU-only WSL guest.
- Healthy worker/scheduler heartbeats and a successful normal SQLite backup
  Task/Run with two inspectable artifacts.
- Enabled native actions exposed through Windows MSAA, normal Stop followed by
  Start, a new desktop instance, and the same account, completed Run and artifacts.
- Final normal Stop and export of the exact installer checked by byte length
  and SHA256. No inference, GPU or external-model result is inferred from these checks.

The existing managed UI Automation observer failed inside Windows' .NET proxy
registration, including from a separate STA observer. That check is **not marked
passed**. Native MSAA separately exposed the named, enabled `Press` actions and
was used for the actual Stop/Start above. Disabled buttons have no default action;
the first overly strict observer incorrectly required one. Narrator and the
managed UI Automation observer remain unqualified on this Windows 10 fixture.
The browser and ordinary native controls were inspected independently.

Portable PowerShell contracts and relevant native PowerShell 5.1 contracts passed.
Release-local checks passed Ruff lint/format, 293 focused Python packaging/release
cases and 1,165 frontend tests, plus frontend lint, typecheck and production build.
Compose configuration and the actual bundled Docker image were validated. An
isolated offline 0.3.1 → 0.3.2 upgrade preserved records in twelve original tables,
artifact bytes and schema 0045; SQLite integrity/foreign keys and the real new API
and UI passed. A separately started broad Python run was stopped after 98 passing
cases and is not reported as a full-suite pass.

Windows 10 local-model inference and physical Windows NVIDIA execution were not
run in this fixture. The earlier Windows 11 CPU first-reply qualification is
separate evidence. Windows 10 21H2/LTSC admission has boundary-test coverage;
actual installation in this change was on 22H2. The installer remains unsigned
under the owner's existing decision. Published 0.3.1 assets/tags are unchanged;
0.3.2 publication follows the human-owned master promotion.
