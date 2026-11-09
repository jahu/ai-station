# Windows automatic update handoff

Continuation of [desktop updates](desktop-auto-update.md). Linux is qualified;
Windows remains outside `QUALIFIED_PLATFORMS` until its own implementation and
native package qualification are complete.

## Fixed boundaries

Preserve the dedicated WSL distribution, disabled interop and disabled host-drive
mounts. Do not add a Windows shell bridge, a public listener, host credentials in
the guest, or a new background service. The existing native Windows supervisor
owns its SID-scoped UI lease, private installation record and exact WSL client.
The control plane keeps its ordinary administrator-owned update Task/Run.

## Chosen transport and ownership

1. A typed guest adapter, available only in the dedicated packaged WSL guest,
   accepts the same finite prepare/inspect/apply/cancel operations as Linux. It
   validates the exact standalone administrator Run and idle gate. Its journal
   stays outside application data, inaccessible through ordinary workspace tools.
2. The Windows target descriptor freezes the installer asset ID, SHA256 and byte
   count. Do not fabricate Linux bundle/image metadata before opening the EXE.
   Backend acknowledgement binds this descriptor to the saved official offer.
   Reuse the native Python official publisher downloader for verified staging of
   the Windows asset. Do not extract or execute a Windows installer in the guest.
3. The existing Windows supervisor polls a finite guest control operation through
   its already-owned `wsl.exe` and recorded distribution. No caller chooses a
   command, executable, path or distribution. Bounded metadata identifies only
   the approved Run/release, fingerprint, package byte count/hash and native stage.
4. Native Windows independently reobserves the fixed official release and verifies
   the same fingerprint. `ReleaseChannel.psm1` supplies that admission. Transfer
   only the approved package through bounded owned WSL stdout into private native
   quarantine, and rehash the host copy before any Stop or execution.
5. An independent native helper freezes its original installation/SID, immutable
   request and target outside guest app data. Normal owned Stop and UI-lease
   release precede silent per-user Inno execution. Preserve the existing unsigned
   installer policy; never disable OS security or force another process to exit.
6. Resolve and verify the installed retained target from its publisher manifest.
   Reuse `Invoke-StationSetup -AllowUpdate` and the preserving guest transaction;
   do not rebuild or reimport the distribution. Restart through the new native
   supervisor, continue first-run state automatically, and confirm actual target
   guest/native readiness before reconciling the original Run and dispatch gate.

## Crash boundaries

Persist intent before native installer dispatch. A lost acknowledgement does not
permit another installer launch. Recovery inspects the exact retained target,
installation registration and preserving guest transaction. Ambiguous partial
installation remains fenced for explicit local inspection/Continue. Confirmed
preparation failure leaves the current app running; confirmed terminal failures
must return typed status, including their explanation, rather than a transport
error that leaves the Run permanently active.

Use handle/lease ownership, not PID disappearance or broad process termination.
Cancellation is available during preparation and transfer; activation retains its
existing preserving transaction and explicit inspection semantics.

## Implementation status

The Windows candidate now includes:

- The shared publisher fingerprint and a second independent native observation of
  the exact official Windows asset, version, byte count and SHA256.
- A finite ordinary-guest bind/poll/export/result/status/authorize protocol. WSL
  interop and host mounts remain disabled. Verified bytes stream over the owned
  WSL client into SID-private native quarantine; no caller supplies a host path.
- An independent helper with a durable original installation/Run journal and
  exclusive ownership. Normal Stop and UI-lease release precede silent per-user
  Inno installation. The installer registers its full native publisher identity;
  recovery verifies that retained target rather than dispatching another EXE.
- The original old/target preserving guest transaction, actual database backup
  proof, automatic target GUI startup, healthy guest/native confirmation and
  completion of the original Run. Local Continue inspects a stopped operation;
  live helper handles and uncertain installer dispatch are never replayed.
- The target bridge migration is pinned to exact old/new source hashes. Both that
  migration and Windows `QUALIFIED_PLATFORMS` admission remain closed until the
  native package test passes. Portable PowerShell tests alone do not open them.

The actual public 0.4.0 release was reobserved through Python and PowerShell;
their fingerprint and selected Windows SHA256 agreed. Regression checks use
fake WSL/installer processes and real binary streams, temporary SQLite databases,
private native journals, canceled transfers and lost acknowledgement boundaries.
These are component results, not a claim of a successful Windows package update.

Native Windows 10 / Windows PowerShell 5.1 checks and preserving bootstrap are
now being exercised on the retained disposable VM. The first native package
exercise found and corrected a missing shared process-module import that was
misreported as an old WSL version. A real owned-child regression now covers that
transport without caller-global imports; WinPS5 informational CLIXML progress is
drained like the production waiter, rather than mistaken for a failed process.

The exercise also found that updating the application Debian package leaves the
rootfs-only `/usr/libexec/ai-station/wsl-control` unchanged. Windows packages now
carry the exact bridge under the protected application manifest. After verifying
the installed target, the root updater atomically publishes only the pinned old
→ new bridge, with an executable mode and fsync, before completing its receipt.
Changed source bytes, foreign installed bridges and symlinks are refused; exact
completed publication is idempotent on recovery. This is an application-owned
WSL file, not a host OS or external runtime migration. Its gate remains closed
until the rebuilt native package exercise completes.

A later actual preparation attempt exposed an isolated Python entry issue: `-I`
does not add a script's directory to imports. Both independent helpers now
bootstrap only their own verified sibling directory, as the desktop launcher
already does. Tests run each real entry without `scripts/` or ambient
`PYTHONPATH`; the actual bundled interpreter also runs both stock `--help`
entries. The qualification observer now follows retained desktop re-execution
and installs its publisher fixture only after the stock helper has imported its
own modules, so it cannot conceal this entry failure. No installed package file
is edited to inject the fixture.

Remaining native qualification covers preserved account/history/artifact bytes,
one-click normal update,
cancellation, interruption/no replay, stock subsequent launch and native UI/icon.
Run WinPS5 checks on Windows 10 and preserve Windows 11 contracts; do not claim
physical Windows 11/GPU testing that was not actually performed.
