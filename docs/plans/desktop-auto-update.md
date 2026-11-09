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

## Implementation checkpoint — 2026-11-09 (candidate, not released)

Release `v0.4.0` was published from the owner's merged master. Anonymous downloads
of all four release assets matched their retained SHA256/size receipts. The live
workstation remains on that qualified release; the changes below are isolated in
the automatic-update feature checkout.

- The footer shows the API version, falling back to the compiled UI version.
  Administrators of installed clients get cached background metadata checks and
  a discreet link when a newer stable release exists. Settings → Updates provides
  manual checks, the exact offered version, notes, package size, one update action,
  progress, pre-activation cancellation and reconnect/reload presentation.
- Checks and install requests use owned standalone maintenance Tasks/Runs.
  Install requests freeze an owned successful observation and an idempotent request
  identity. The shared release parser and native downloader admit only the fixed
  publisher's stable version, package identity, byte size and SHA256. The actual
  public 0.4.0 metadata matched through both control-plane and native transports.
- The native Linux candidate retains verified Debian contents without root or
  package scripts, records the running bundle after healthy startup, and follows
  its verified active receipt on later launches. An independent helper journals
  preparation/application outside application data. It reuses the existing native
  handoff and offline backup/image transaction, rather than rewriting those layers.
- The typed private native bridge accepts only capabilities, prepare, inspect,
  apply and cancel. Installation coordinates come from the desktop supervisor.
  Native SQLite reads recheck the exact owned administrator Run, its current
  worker claim, parameters and idle gate before Stop. No caller supplies an
  executable, destination, shell text or replacement publisher URL.
- The short trusted coordination transaction takes an idle gate only after active
  work finishes. Both selection and atomic claiming test that gate; queued work
  stays durable. Restart recovery inspects the original native journal and can
  complete history and release the gate in one database commit without repeating
  the installer. An uncertain activation retains its inspection fence.
- Windows source now embeds the existing brand icon in the executable, installer,
  window and tray. Setup shows one primary action for its current stage. Failure
  explanations survive read-only status refreshes. Portable PowerShell parsing
  and the existing 15 file/lease/hash assertions passed; new native appearance
  and automatic Windows application are not qualified yet.

Normal tests use synthetic packages, accounts and native replies; they do not
change the running station, start Windows, load a GPU or fetch model weights.
Focused tests cover metadata hostility/bounds, transfer hashes, canonical file
boundaries, extraction, retained launch selection, administrator revocation,
cancellation, idle dispatch, native duplicate requests, uncertain activation,
and original-operation restart recovery. Frontend tests cover the footer, update
offer, exact one-click request and restart presentation. These are component
proofs, not a real installed old→new update claim or final full-suite validation.

**The native Runner's `APPLY_QUALIFIED` flag remains false.** The application must
not offer an operational Update button through the real Runner until the
packaged apply, restart and recovery gates pass. Test fixtures explicitly opt in
only inside their isolated tests.

Remaining delivery gates:

1. Finish interrupted native Linux application/resume and validate actual full
   packaged old→new preservation, owned shutdown, healthy restart and subsequent
   launch. Harden any failures found; do not flip admission merely for progress.
2. Implement the independent Windows publisher-download/silent per-user installer
   handoff and preserving WSL update/restart/reconciliation. Validate Windows 10/11
   contracts; boot the retained Windows fixture only for the frozen native candidate.
3. Capture the actual new native installer and neutral browser setup. Build the
   separate illustrated `/install/` guide, landing/README links and accurate notices.
4. Review the complete diff, run final applicable backend/Runner/frontend/package/
   Compose/image checks, update qualification and versioned release documentation,
   and deliver PRs to develop. Only the owner promotes the release to master.

## Native recovery continuation (candidate)

The follow-up separates trusted native Resume from normal worker dispatch.
Activation journals a private top-level marker before Stop. It freezes the exact
local Docker connection and verifies the supervisor's recorded daemon before
image operations; changing contexts must never select another installation.
Normal startup can adopt an already-applied coordinator result, but unfinished
application needs local Continue approval (or explicit `--resume-update`). An
active original helper is never launched again. Resume inspects its existing
command identity and publishes only a prepared transaction; an already-applied
publication is not repeated. Confirmed abort can reopen the verified previous
bundle. The marker is removed only after matching publication/readiness or a
verified abort, never merely because a PID disappeared.

After local recovery, a trusted worker reconciles the same interrupted Run from
native proof. Its inspection transitions and dispatch-gate removal are one
transaction, with original claim provenance retained. They call no executor or
installer and expose no queued interval to other workers. Real packaged Linux
and Windows qualification, Windows automatic handoff and the illustrated guide
remain delivery gates; this continuation does not enable native apply yet.

The first real packaged Linux startup exposed a missing explicit Runner socket in
normal Linux configuration. Namespace admission now derives exactly the same
`data/runtime/runner/runner.sock` as the existing launcher when that optional key
is absent. Explicit socket identities remain unchanged. A regression uses an
actual freshly generated Linux configuration rather than the Mac-style fixture.
The failed package attempt remains recorded; rebuilt-package qualification is
still pending and admission remains closed.

The first real preserving-update attempt also exposed standard Linux `/var/run`
Docker aliases and operation errors being mistaken for control-protocol errors.
The native client now pins the canonical socket and still attests the original
supervisor daemon. An operation's `error` explanation remains part of its typed
status; the protocol's error-only envelope still rejects invalid requests.
Regression tests exercise a real local Unix listener and the private control
channel, including failure/inspection statuses. Neither attempt altered live
user data; their isolated receipts/logs remain available for diagnosis.
