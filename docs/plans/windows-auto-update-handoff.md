# Windows automatic update handoff

Continuation of [desktop updates](desktop-auto-update.md). Linux and dedicated
Windows/WSL are qualified. The Windows gate and exact bridge migration are now
enabled after native qualification; the chronological findings below retain the
failed attempts as well as the final proof.

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

The next real preparation exposed a control-channel timeout: hashing the whole
retained bundle, including its large image archive, blocked the five-second
prepare acknowledgement. Worker recovery expired the uncertain claim before the
helper could validate it. Full source verification now runs in the independent
helper's observable preparing phase, before any download. It checks the frozen
source identity and all manifest hashes, then rechecks cancellation and live
authority. The control handler only journals and dispatches the fixed helper;
timeouts and worker ownership rules are unchanged. Regression tests cover both
platforms, modified source identities/bytes and cancellation during hashing.
This fix still requires a rebuilt native package exercise.
That exercise also caught a platform mix-up in the shared source verifier: its
Linux-only compatibility predicate rejects Microsoft WSL. The shared verifier now
requires the caller's platform validator explicitly; Windows supplies its
dedicated-guest validator. Windows staging regressions keep native-Linux support
disabled, matching WSL instead of inheriting the Linux development host's result.
The refused Run finalized as failed with its gate cleared and no native installer
dispatched. A stock fresh PowerShell process could still open and Stop the app.

Guest readiness also validates its bound native identity without requiring the
interactive update channel's 60-second presence lease. A cold startup may exceed
that lease; recording real healthy startup does not renew it or authorize a new
update. Capabilities and new preparation/apply requests retain fresh-presence
checks, and a wrong native version/channel still refuses the readiness receipt.
After real healthy startup, the native finisher rebinds the exact registered
target immediately before acknowledging completion. That preserves the final
acknowledgement's fresh-presence check even when startup exceeded 60 seconds.
The component regression covers the complete finisher order and rejects replay.
Another recovery regression reproduced a lost child-exit acknowledgement after
the finisher had persisted its proof: the parent wrote its stale pre-child copy
over the newer journal. The parent now retains only the same frozen operation's
newer restarting/completed proof. Explicit Resume verifies the existing guest
acknowledgement without another installer, Stop or guest transaction; proof for
a different source remains refused. Both incomplete and completed child writes
are covered by the native stage tests.
Inspection and explicit Resume now consider both the parent helper's and the
independent finisher's exclusive handles. A regression reproduced a second child
dispatch while only the finisher remained alive; both live owners now block it.
The actual progress capture also exposed a visible Start button during updating.
The shared native button synchronizer now hides conflicting lifecycle actions,
disables keyboard/tray Stop, and offers Continue only for an abandoned operation.
Its source is exercised with portable controls and real WinForms controls on
Windows; normal startup/setup behavior is retained.

The first rebuilt pair was refused by the real API identity check before any
update request: its private version bump changed package declarations but missed
the two runtime `__version__` literals. Stable packaging now compares both runtime
literals with backend/Runner/frontend declarations, without importing application
code. Clean but inconsistent, duplicate or executable declarations are rejected.
Qualification uses a new consistently numbered pair; the refused pair is not
successful update evidence.

The first real native transfer was held by a qualification-only callback:
PowerShell mutates a saved FunctionInfo when that function is replaced, so the
fixture recursively invoked itself. The exact owned fixture was stopped before
activation and its original Run was failed through the typed native channel.
The fixture now replaces only publisher metadata; the transfer is unmodified.
A read-only reference export then verified all 881,758,787 package bytes and
their SHA256 in about 35 seconds. The original async receiver obtained only
474,218,496 bytes before a deliberately bounded 90-second observation canceled
it; small memory/file cases passed. Its per-fragment fixed sleep is replaced by
an interruptible task-completion wait. Completion, faults and cancellation stay
tested, and transfer failures retain bounded source diagnostics only in the
SID-private native store. Full packaged transfer/install qualification remains
required; these diagnostic Runs never dispatch an installer.

The corrected receiver transferred all approved bytes with matching SHA256 in
39 seconds on Windows 10. Actual administrator cancellation also finalized its
original Run without dispatching an installer. The next packaged attempt applied
the native/guest target and retained its backup proof, but failed at automatic
startup: the UI's Details dialog reported a sharing violation on `install.lock`.
The finisher's read-only `open` polling acquired the same exclusive installation
lease needed by the target UI's initial status/start. That first status failure
left the UI stopped. Readiness now uses the existing fixed ordinary-guest `open`
operation with private-root/registration validation, without an installation
lease; final binding and acknowledgement still acquire the real lease. Native
regressions reject a retained lease or the old lock-taking readiness path. The
failed attempt is inspection evidence, not successful one-click qualification;
the corrected packaged restart and subsequent launch still need verification.
Stock startup exposed a second expiry boundary: verifying/copying a retained
bundle can exceed 60 seconds before installing its Windows lifecycle adapter.
The app then served real health without recording the new native readiness
receipt. Adapter selection now accepts the exact installed binding independently
of its age. Capabilities and prepare/apply still require fresh native presence;
neither selecting the adapter nor recording health renews permission. Regression
coverage distinguishes an expired matching binding from a wrong-version binding.

The corrected 0.5.11→0.5.12 private package exercise completed automatically:
native installer, preserving guest transaction, real target readiness and the
original Run's `succeeded` status with its dispatch gate cleared. An existing
account authenticated afterward; the same nonempty conversation, two messages
and four artifact hashes matched the pre-update snapshot. A deliberately lost
host acknowledgement recovered through the actual native Continue button with
the same running instance, native payload, guest installation record and proof.
The UI then exposed a separate result-envelope defect: Resume dispatched safely
but returned zero objects, which its background lifecycle reader correctly
rejected. Resume now returns one original-Run dispatch receipt; failures still
throw and live-owner checks are unchanged. The new receipt contract and final
stock launch need their last native UI checks before admission opens.
The native shutdown review also found that a tray Stop requested during a
background status job was latched but never drained. The UI now dispatches that
same normal Stop after its current job finishes, waits for a live startup client,
and closes only after confirmed shutdown. An exit request also prevents a queued
automatic startup from reopening the app. Source-level UI policy regressions
cover deferral, single dispatch, startup ownership and idempotent close.

## Final qualification — 2026-11-09

- A real private installed **0.5.11 → 0.5.12** update completed native Inno
  installation, the preserving WSL transaction, automatic stock UI/guest restart,
  and the same administrator Run's `succeeded` state. The dispatch gate cleared.
- Account credentials, one nonempty conversation, two messages and four artifact
  hashes matched before/after. The existing account authenticated afterward.
- The archived root-owned transaction also proves the real **0.4.0 → 0.5.0**
  bootstrap and exact `caff9096…` → `76961bbe…` bridge migration completed.
- Real pre-activation cancellation retained the running source without an
  installer dispatch. Explicit native UI Continue recovered a deliberately lost
  host acknowledgement with the same running instance, native registration,
  guest installation record and completion proof, without replaying an installer.
- The final result-envelope/tray fixes were checked in a normally built native
  payload against the registered packaged guest. Actual Continue returned to
  **Running locally** without stale errors. Stock guest startup used no publisher
  override. Actual tray Stop/exit released the UI owner and process; the guest
  stopped, SQLite integrity was `ok`, and all saved record/file hashes still matched.
- All 15 manual-CI native contract scripts passed in fresh Windows PowerShell 5.1
  processes, including real WinForms controls. The dedicated fixture was Windows
  10 build 19045.6456, CPU-only, without host-drive mounts or GPU passthrough.

Publisher observations/cache were explicit private fixtures; no fake GitHub
release was published. Receipts are retained privately under
`data/acceptance/windows-auto-update-native-20261109/`, notably results 095,
112–113, 122, 124–128. Initial recovery/CLI fixture failures remain recorded and
are not counted as passes. These checks do not claim physical Windows 11/GPU
qualification. Release promotion/publication and the guide's additional native
Windows capture are separate remaining delivery steps.


### Final local verification

The complete partitioned Python baseline passed **9,117 tests with 25 platform
or explicit opt-in skips**. After the final native handoff fixes and Windows
admission, all **403 tests in the 20 affected update/package/Runner files** passed
(`PYTHONPATH` pointed at this checkout, including subprocesses). Repository-wide
Ruff lint and formatting passed for **1,253 files**; `git diff --check` passed.
The 15 native Windows contracts above run in separate PowerShell 5.1 processes
in the manually dispatched CI operation too, so fake module functions cannot leak
between scripts. No automatic or paid hosted CI was enabled.

The unchanged frontend's prior lint, typecheck, production build and 1,176 tests,
plus Compose/image verification from the update foundation, remain the applicable
baseline. Private frozen target packages were also built and exercised through
real Docker/guest startup. This PR changes no frontend or Compose/Dockerfile
configuration. No GPU inference or physical Windows 11 result is claimed.
