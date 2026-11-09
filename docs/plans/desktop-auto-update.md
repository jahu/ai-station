# Desktop updates and simpler installation

User goal, 2026-11-09: installed AI Station proposes a newer official release and
updates after one click, without the operator downloading or opening another
installer. Show the running version discreetly. Give Windows its real app icon,
simplify first setup, and publish a separate illustrated installation guide.

## Existing foundations

- Linux packages already retain verified application bundles under the private
  desktop root. `desktop_versions`, native owner handoff and the offline image
  upgrade coordinator provide identity, exclusive ownership, backup, migration
  and interrupted-update fences. Their Mac presentation/admission stays gated.
- Windows has a per-user installer, retained native payloads, an owned WSL guest,
  verified package streaming and a preserving guest update. Release 0.4.0 fixed
  ordinary XDG-parent admission and pipe-error cleanup. Reuse that transaction.
- The browser/control plane has accounts, administrator checks, durable Runs,
  maintenance/backups and a typed private Host Runner. It has no Docker or host
  installation authority, and receives none through this feature.
- No current release discovers and installs a newer public release automatically.
  The new client is required once before subsequent one-click updates work.
  Describe that bootstrap honestly; do not modify arbitrary old checkouts.

## Operator experience

1. Sidebar footer shows the running API version, with build-version fallback
   while reconnecting. A subtle available-update indicator links to Settings →
   Updates. Normal conversation remains the primary workspace.
2. Installed desktop clients check the official stable release at startup and
   at a bounded cached interval; provide Check again. No models, personal data,
   prompts or credentials are sent. Development checkouts show their version and
   an accurate installation status rather than offering an unsafe self-rewrite.
3. Show current/new version, release notes, download size, and **Update and
   restart**. That click authorizes this frozen release only. No second installer
   wizard or application confirmation. Native OS permission prompts, if a fresh
   prerequisite actually needs them, retain their real OS meaning.
4. Download/check progress stays inspectable. Preserve accounts, conversations,
   agents, models, files and settings. If work is active, wait for an idle safe
   point; do not kill jobs. Fence new dispatch during the maintenance handoff.
5. Reconnect to the same station after restart, confirm the new version, and
   complete the original update Run from native evidence. Failed downloads leave
   the old version running. Interrupted application needs bounded reconciliation,
   not an automatic second installer or destructive rollback.

## Release admission and native execution

- Only the fixed official `jahu/ai-station` GitHub stable release channel; no
  user/agent-supplied URL, executable, command, destination or repository.
- Freeze release/tag, numeric version, asset identity, byte count and GitHub's
  SHA256 digest. Reject drafts/prereleases, malformed/ambiguous assets, downgrades,
  unsupported platforms, missing integrity evidence and changed observations.
- Checking and preparing updates are administrator-authorized ordinary
  Task → Run → Events operations. Native installation authority belongs to the
  desktop owner, behind typed operations and its private installation receipt.
  A normal agent/tool cannot acquire it by writing an artifact or task parameter.
- Download to owned quarantine with size/disk/time bounds; verify before Stop.
  Keep the native updater independent of the API/worker it replaces. Record the
  exact operation outside mounted application data and reconcile its identity
  after restart. Recover from that receipt rather than blindly redispatching.
- Linux: reuse verified retained bundles and the existing offline backup/image
  transaction. Extract only validated package contents into private staging;
  activate the new user-owned bundle without changing OS packages or requiring
  Docker access in the browser. The installed launcher follows the verified
  active version; preserve the current package/data namespace and prior payload.
- Windows: reuse the verified per-user publisher package silently through a
  detached native owner, then the existing preserving WSL transaction. Normal
  Stop/exit releases native file/UI ownership before replacement. Retained
  payload manifests identify the target; new startup follows the verified target.
  No credential copying, driver changes, unrelated distro/process control or
  unqualified macOS enablement.
- Existing unsigned-Windows policy remains explicit. HTTPS publisher identity
  plus server-computed asset hashes provide the current release trust boundary;
  do not describe checksums as a publisher signature.

## Windows first-run presentation

Use the existing brand icon in the installer, executable, window and tray.
Present one clear primary action for the current step: set up, install required
Windows support, continue, or open AI Station. Keep optional diagnosis secondary.
During work show a clear stage and Cancel where cancellation is safe. After setup
open the browser automatically. Keep Stop available when running. Preserve a
failure explanation until the user acts instead of hiding it on a status poll.
Do not weaken WSL/OS checks or make a root/system installer the default.

## Separate illustrated guide

Publish `/install/` on the existing static website, with a small landing-page and
README link. Give Windows 10/11 and Ubuntu paths, prerequisites, normal setup and
restart steps, first account/model setup, unsigned-Windows notice, update flow
and focused troubleshooting. Match the released UI and use genuine captures from
neutral QA installations only. No personal Library/chat, private URLs, setup
tokens or invented screenshots. Preserve the existing visual language and mobile
readability; support keyboard use and direct links without JavaScript.

## Delivery and proof

1. Version footer, native icon and first-run presentation; inspect actual desktop
   and narrow-screen UI, and the native Windows window/installer.
2. Fixed release observation and admission, explicit update permission, API/Run
   wiring and status UI; test hostile metadata, privacy, duplicate requests and
   an offline/unavailable publisher.
3. Native download, ownership handoff, idle/dispatch fence, preserving apply,
   restart and recovery on Linux and Windows. Test cancellation before apply,
   corrupt/truncated downloads, changed targets, active jobs and interrupted apply.
4. Real packaged old→new update in isolated Linux and retained Windows fixtures;
   retain account/history/artifact hashes, show the new version, and verify a
   normal subsequent start. Use clearly labeled publisher fixtures until a second
   real updater-capable release exists; never publish a fake stable release.
5. Illustrated guide, README, release/publisher assets and exact qualification.
   Review/validate PRs into develop; human owner alone promotes to master.

These are completion gates, not already-qualified capability claims. Reuse the
current workstation preview and existing test fixtures. Keep the Windows VM off
until a frozen native candidate needs qualification, then shut it down normally.

## Implementation checkpoint — 2026-11-09

Release `v0.4.0` is published from the owner's merged master. All four public
assets matched their retained SHA256/size receipts. The live workstation remains
on that release; qualification below uses isolated native desktop installations.

### Delivered foundation

- Sidebar version, cached administrator update checks and a subtle available-update
  link. Settings → Updates shows the exact release, notes, package size, one
  update action, progress, pre-activation cancellation and reconnect/reload.
- Owned standalone maintenance Tasks/Runs freeze the official release fingerprint
  and an idempotent request identity. The native owner reobserves the publisher,
  verifies package bytes, and retains the exact bundle outside application data.
- Atomic claims honor the idle dispatch gate. Activation uses the existing native
  handoff and offline image/database backup transaction. Recovery inspects the
  original operation; it never repeats an uncertain installer dispatch.
- Windows source embeds the existing brand icon in the executable, installer,
  window and tray. One primary action follows the current setup stage, while Stop,
  cancellation and failure explanations retain their existing contracts.

### Native Linux update and recovery

**Linux x86-64 is qualified for native automatic application.** The Runner's
`QUALIFIED_PLATFORMS` admits `linux-amd64` and the separately qualified dedicated
`windows-x64` guest. macOS is not admitted.
Development checkouts without the installed supervisor cannot self-update.

Activation freezes the exact local Docker connection and the already-attested
supervisor daemon ID in a private marker before Stop. Cold recovery verifies that
original daemon even after ordinary shutdown removes the active Compose receipt.
Changed or missing identity requires inspection. A live original helper is not
launched again; local Continue (or `--resume-update`) finishes an interrupted
operation. No Runner/agent Resume operation exists.

The original coordinator request binds the source/target bundle and namespace.
Completion reuses its actual transaction-receipt validator for operation, backup
and schema proof, followed by the new supervisor's healthy ready receipt. A
confirmed abort may reopen only the verified previous bundle. Private native
logs retain early restart errors. A PID disappearing is not completion evidence.

Trusted workers reconcile the same interrupted Run and remove its own dispatch
gate in one transaction. Rechecking the current claim/state after native IPC
prevents a second inspector from publishing a duplicate result. Queued/claimed
reconciliation transitions never expose a dispatchable interval or call an executor.

Actual installed qualification used clean frozen **0.5.0 → 0.5.1** candidates:

- One administrator HTTP request used verified Debian bytes from a frozen package cache,
  stopped the owned desktop, applied the actual offline image/database transaction,
  restarted the target and completed the original Run. Account/conversation rows
  and artifact bytes matched before/after hashes; the gate and marker cleared.
- The unmodified old launcher subsequently followed the verified new bundle.
  Login and the saved conversation worked; normal Stop completed.
- A one-shot qualification-driver exit after actual Prepare and before Publish
  exercised cold interruption. Explicit native Resume completed the original
  operation with exactly **one Prepare and one Publish**, then restarted and
  reconciled the same Run. Preservation and a subsequent stock launch passed.

Publisher metadata and package cache were explicit fixtures; no fake stable
GitHub release was published. The packages, independent helper, native ownership,
Docker transaction, database backup, restart and stock subsequent launch were real.
No GPU, model download, live user data, Windows VM or unrelated container was used.

Real package tests found and fixed implicit Linux Runner-socket admission,
canonical `/var/run` aliases, operation-error transport handling, the shared
coordinator receipt contract and daemon-proof retention across Stop. The failed
attempts remain recorded with the successful qualification; failures were not
waived. Normal regression tests now exercise actual Linux-generated configuration
and private Unix listeners as well as synthetic owner/coordinator fixtures.

### Verification and remaining delivery

The foundation passed 9,061 Python cases with 25 platform/opt-in skips, 1,176
frontend cases, lint, formatting, TypeScript, production build, Compose validation
and Docker build. Its six Debian-fixture mode failures were corrected and the
whole affected file passed under both private and normal umasks. Follow-up native,
coordinator, worker/Run and concurrent-inspector regressions passed; exact reviewed
head and per-command results are retained with local acceptance receipts.

Remaining gates for this user goal:

1. Linux review, packaged update/recovery and the merge to develop are complete.
2. [Windows handoff](windows-auto-update-handoff.md) and native qualification are
   complete: preserving installed update, same-Run reconciliation, cancellation,
   actual UI Continue without replay, stock startup, clean tray shutdown and
   nonempty saved-history/file hashes. Windows admission is enabled. The retained
   CPU-only fixture was shut down normally after qualification.
3. The new native Windows presentation passed real WinForms/UI checks. The
   separate illustrated `/install/`
   guide is merged to develop and checked on desktop/mobile without JavaScript;
   its first-account screenshot was approved by the owner. A genuine neutral
   native Windows Start screen has also been captured privately, without personal
   files or setup tokens. Its public use awaits the owner's standing image review.
4. Final 0.5.0 Linux/Windows assets, QA ZIP and SHA256SUMS are built and checked;
   identities and exact verification scope are in [release notes](../releases/0.5.0.md).
   Finish the guide image review and feature PR, then prepare the bot-authored
   release PR. Only the human owner approves and merges that PR to master.

Linux and Windows execution qualification is complete. The overall user goal is
not reported delivered until the remaining guide capture/release steps are ready;
only the human owner may approve and merge the release PR into master.
