# macOS consumer installation — NR-13/14

Status: implementation contract, not an available Mac installer. The full release
still requires a real local Mac installation and first result; a remote web client,
Linux emulation or an unsigned skeleton does not satisfy it. Preserve the Docker
control plane, native user Runner and Task → Run → Events → Artifacts lifecycle.

## Explicit search-image preparation (candidate, 2026-11-03)

The actual package GUI qualification now also has candidate native full-backup
and restore steps after the real conversation/restart checks. XCTest operates
the retained product helper's ordinary selection and confirmation dialogs, then
selects the exact newly created backup through the native folder picker. It
neither calls backup APIs nor bypasses consent. Read-only observations require
a new desktop owner on the same private origin, hash verification of every
exported file and unchanged conversation history. Restore must invalidate the
old session, accept the original password, recover that exact history and remove
a synthetic conversation created after export. The backup must remain valid.
These steps are unqualified until their real Mac run passes; preserving update,
removal, signing and applicable hardware acceptance remain independent gates.

The following candidate removal/reinstall stage stops the station normally,
hashes the real VM database and retained files, verifies a separate reinstall
copy, then removes only this fresh experiment's generated `.app`. It must prove
the private configuration, database and files are unchanged while the app is
absent. Reinstalling the identical verified bundle must retain the session and
complete conversation and produce another real native-model answer. An existing
reinstall copy, redirected app or data inside that app refuses removal. This is
actual filesystem lifecycle acceptance on an owned disposable app, not Finder,
Gatekeeper, signing, a preserving version update or a completed installer claim.

Run 41641007361 at `fa1c29b` ended before the control-plane build: the optional
GitHub stage publisher raised on a nonzero CLI result, aborting the actual
experiment. Its evidence points to `macos_qa_status.py:post`, not a product
startup fault; the underlying publication failure reason is unproven. Publication
now has three five-second attempts and a fixed nonsecret warning on exhaustion.
Its absence is recorded, but the experiment continues to its actual application
outcome. Owner/repository/token guards still fail closed, and functional failures
are still failures. The native UI component at that head passed all five fixtures;
neither result qualifies the complete installed application.

Real GUI run 41600426425 reaches `starting_services` with a live native Runner
and Docker Compose still waiting; no project containers are observed. This
narrows the startup failure but does not establish its complete root cause.
Compose currently may download the pinned SearXNG image during the application's
180-second readiness window. Its `--wait-timeout` bounds container health, not
that download. Prepare this fixed prerequisite separately, with visible native
progress and cancellation, before starting application services. Verify the
Linux architecture against the package, use the already pinned local engine,
and require cached images during Mac `compose up`. Never modify Docker settings,
remove images, substitute an unpinned image or extend the readiness deadline to
hide a failed startup. Cached startup must remain offline-capable. The next real
GUI run must verify this candidate; component tests alone are not acceptance.

## Current code and verified upstream constraints

GUI run 41606316157 completes separate search-image preparation but fails the
native Runner's 20-second readiness gate before containers are created. That is
a distinct remaining failure, not proof that all startup is fixed. The existing
installed-interpreter component already exercises a real private Runner under
a console parent. Extend the native-only matrix with the same installed Runner
under the stock AppKit launcher and nested Python owner. Record bounded import
timings and exit codes without command arguments, environment or raw messages.
This needs no Docker/image/model preparation and must retain the 20-second gate;
it is a diagnostic component check, never full consumer qualification.

Native matrix 41612665516 at `e4d953d` passes that real AppKit/installed-layer
component on ARM and Intel: readiness takes 2.07 and 2.74 seconds, respectively,
with unchanged installed bytes and no model/Docker. This does not reproduce the
full installer failure. The next component uses a relocated package copy with
the producer's actual permissions. Full startup faults also distinguish an exited
Runner (numeric exit code) from a live readiness timeout; neither outcome logs
private messages or changes the existing deadline.

The relocated-copy diagnostic at `6fae25f` also passes on ARM/Intel (2.73/3.86
seconds) with the actual producer permissions and stock filtered desktop
environment. The full installer context is still unqualified. The next complete
probe explicitly sets the local `AI_STATION_RUNNER_STARTUP_PROFILE=1` diagnostic:
only the fixed native entry gains Python import timing. Startup evidence keeps
known public module names/timings, exception classes, basename/line frames and
fixed ownership/path fault codes; messages, environment values and private URLs
remain excluded. Normal desktop startup does not enable profiling.

Full diagnostic run 41617862538 at `4cf75db` ended with GitHub's hosted-runner
lost-communication annotation. The application probe did not publish a stage;
the job left its prerequisite step unfinished and no final application report
or downloadable job log was available. This is neither an application failure
diagnosis nor a passing installer. Add fixed, bounded stage breadcrumbs before
each fresh Desktop prerequisite (download, checksum, mount, signature, install,
boot) using the same owner-dispatched status publisher. A new explicit run can
then distinguish a lost prerequisite host from the known application-startup
failure. It still cannot qualify unexecuted consumer steps.

The manual workflow now defaults `macos_startup_profile` to **false**. Only an
explicit true selection enables the fixed native import profiler; inherited
profiling flags are cleared. The experiment records this boolean separately from
its consumer result. A default run and a diagnostic run can therefore use the
same source without treating a timing-altered startup as proof of normal startup.

Run 41625130875 at `3f0a810` starts the real Runner (app import about 6.36
seconds), but reaches the native supervisor's service-readiness failure. Its
post-failure container list is empty after cleanup; that cannot establish that
no containers were created. Capture the owned project's fixed service/health
states during startup, before cleanup, with known exception classes and basename
frames from bounded startup logs. Raw logs, healthcheck output and private values
remain excluded. The next default, unprofiled run must resolve this service gate.

That trace also exposes a composed-budget defect: the native child spends about
72 seconds on package/storage attestation before starting the Runner and begins
Compose around second 88. The original parent's 180-second whole-child window
leaves only about 92 seconds for Compose's existing 120-second health budget.
The candidate therefore bounds native preflight separately (180 seconds), then
starts the existing 180-second application-readiness window on the first fixed
`starting_runner` phase. Total startup remains bounded by 360 seconds; repeated,
late or malformed phases cannot reset it. Runner readiness (20 seconds), Compose
health (120 seconds), early child failure, Stop and Linux/WSL startup are unchanged.
This permits the child to report its actual health outcome; it does not establish
that the remaining service-health problem is fixed. Actual default installation
must still pass all gates.

Default run 41633712343 at `35b2489` reaches real browser readiness without
profiling: all five services are running, and API/search/connection healthchecks
are healthy. The visible first-admin test creates an account and reaches Models;
the independent observer then fails login. The fixture appended `QaAdmin` to the
product's prefilled `admin` username rather than replacing it. A fresh compiled
browser/real-loopback-API reproduction confirms account creation succeeds in
both cases, but observer login returns 401 after append and 200 after explicit
replacement. No model, GPU or production data is used. Keep the helpful product
default; fix the native test to select all, replace and assert its chosen name.
HTTP failure evidence now includes only the numeric status, never a URL, body or
credential. Evidence: `data/acceptance/macos-consumer-qualification-20261102/`
under `default-services-result.private.json` and `account-browser-reproduction/`.
Actual Mac engine/model/reply/Stop and later installer gates remain unexecuted.

The next guided acceptance increment must send a long fictional request in the
ordinary conversation, observe nonempty streamed text while Stop is available,
and click that visible button. Read-only API checks must independently confirm
the new Run is canceled, its partial answer survives and the composer is idle.
The later application restart must preserve that same history. No API cancel,
injected token, shortened fake generation or successful-but-already-finished
answer may substitute for this gate. This check is a candidate until its actual
native/browser/model run passes.

The unmerged consumer-qualification candidate replaces the Linux-only preflight
with a read-only Mac package/OS/architecture and pinned local Docker Desktop
check. This is preparation for the actual installed journey, not qualification.
Do not merge/admit that startup change based only on native unit or neutral-image
bundle checks. Its next gate is the real verified package with Docker Desktop,
first administrator, guided model preparation, first CPU reply, Stop/restart,
preserving update, cancellation/recovery, full backup/restore and removal.

Native end-to-end acceptance should drive the stock application using
[Apple XCUIAutomation](https://developer.apple.com/documentation/XCUIAutomation),
alongside the real browser/API flow. Do not add an automatic-consent switch to
the shipped application or substitute patched dialogs/prerequisites for this
gate. Apple documents a separate Xcode Helper accessibility consent for native
[UI tests](https://developer.apple.com/library/archive/documentation/DeveloperTools/Conceptual/testing_with_xcode/chapters/09-ui_testing.html).
Inspect the fresh QA host's actual capabilities; do not mutate an existing
workstation or edit TCC databases to manufacture a passing result. Missing native
UI permissions are an explicit qualification gap, not an inferred pass.

The separate manual `macos-native-ui-checks` experiment compiles the unchanged
native source into an Xcode test application and drives secure fields, explicit
MFA acknowledgement, restore review and folder-picker Cancel using system UI
automation. It uses a standard free public Intel host, no Docker/model and no
OS permission changes. This establishes native UI automation availability and
control behavior, not the complete distributed package or installed journey.

[Actual system UI run 41531861624](https://github.com/jahu/ai-station/actions/runs/41531861624)
passed all four tests on Intel macOS, without skips or OS permission changes.
It exposed a real presentation defect: modal helper processes never entered
`NSApplication.run`, so they had not completed application launch and their
controls were unavailable to accessibility. Modal helpers now explicitly call
`finishLaunching`; the main application and progress windows retain their normal
event loops. Queries target the actual dialog, excluding duplicate Touch Bar
buttons. This verifies the controls, not a successful full-package installation.

The subsequent directly spawned helper check exposed a separate packaging gap:
the old `Resources/bin/ai-station-native` process has no application bundle
identifier. The actual host-launched check reports `Observed helper bundle: none`
in [run 41544244142](https://github.com/jahu/ai-station/actions/runs/41544244142).
Apple documents that [unbundled applications lack this identifier](https://developer.apple.com/documentation/appkit/nsrunningapplication/bundleidentifier).
The candidate now uses a self-contained `AI Station Helper.app` with its own
`io.ai-station.presentation` identity. Its pure packaging helper is shared by
the product and system UI fixture; the test attaches to the actual host-launched
PID and executable, without launching a substitute. XCTest's generated runner
is sandboxed, so the ordinary QA host owns subprocess creation and cleanup;
no sandbox/TCC entitlements or system permissions are changed. Hashes bind the
helper binary and Info.plist, and old retained packages still use their original
verified single binary. The helper stays inside the existing retained resource
tree; complete outer-bundle code placement, signing/notarization and full native
consumer acceptance remain required release gates.

[Run 41545584872](https://github.com/jahu/ai-station/actions/runs/41545584872)
passed all five system UI cases with this shared helper bundle. The additional
case verifies the host-launched PID, exact executable and application identity,
then operates its actual recovery dialog and cancels it. The host independently
checks clean exit and the private cancellation reply. This closes the helper's
identity/accessibility gap, not the full installed consumer journey.

The separate manual `macos-consumer-backend` job reuses the fresh-host, fixed
Docker Desktop installer guards and builds the real native Python, Runner,
interface, control-plane image and `.app`. Its explicit CPU model fixture is the
existing Huihui Qwen3 4B Q4_K_M catalog entry (2,497,281,312 bytes; pinned SHA256
`b1324e2f1bd2e0610d591f54f93e38d90b187f69d1f215f4cace349eade678d7`).
It exercises the existing console entry, real first-admin API setup, native engine
and model preparation, first reply and preserving Stop/restart. It neither patches
prerequisites nor installs into an existing station. Its result explicitly leaves
consumer GUI, update/backup/restore/removal and complete installer qualification
false; those remain required acceptance, not replaced by this backend evidence.

[Backend run 41541859567](https://github.com/jahu/ai-station/actions/runs/41541859567)
was canceled for exceeding 45 minutes; both official run and job log endpoints
returned no usable log afterward. The last reached application stage and cause
are therefore unproven. Do not infer success, an application memory failure or
even completed package assembly from that result. The subsequent QA candidate
publishes fixed stages and advisory RAM/swap/disk figures directly as a per-run
[commit status](https://docs.github.com/en/rest/commits/statuses), independent of
the final job log. Only this owner-only job gets `statuses: write`; the publisher
retains its short-lived token privately and drops CI authority before subprocesses.
Failures are recorded before cleanup. This does not replace functional assertions.

[Actual backend run 41551172141](https://github.com/jahu/ai-station/actions/runs/41551172141)
built and started the real package and created its first administrator. The
ordinary native SDK preparation Run then reached `running` and failed. No model
was downloaded and no inference/restart acceptance follows. Stage observations
reported about 6.8 GiB available RAM and zero swap at SDK dispatch; they do not
establish a memory-related cause. The original generic QA exception discarded
the underlying native fault. Terminal Run diagnostics now retain its validated
identity/error code and stderr traceback file/line/function coordinates, exception
class and numeric OS/HTTP codes, without publishing message text, URLs, account
fields, prompts or source lines. Inspect that evidence before changing SDK code.

The producer also restarts only its newly installed Docker Desktop after package
assembly and before starting the station. The same-run, private installation
receipt must match before any such action. This clears the developer build's
transient guest cache, matching a consumer who imports a prebuilt package; it
does not alter Desktop settings, image storage, the pinned model/context or a
user's existing services. Runtime RAM admission remains unchanged and still
checks actual available memory. The reported figures must establish whether
memory pressure is relevant; it is not an assumed explanation for the lost run.

The pending `macos-consumer-gui` mode reuses that same real package and fresh-host
setup. The ordinary host launches the stock `.app` with no console or approval
switches. A separate XCTest class verifies the actual application PID/executable,
clicks its real setup consent, attaches to the system's default browser and fills
the first-administrator form. It must reach the actual model setup page; the
ordinary API login then independently confirms the account was created. Logs
remain private because browser diagnostics can contain a setup URL. The ordinary
component UI operation explicitly selects its five fixture tests instead.

This mode has not yet been qualified. Its next implemented UI stages separately
review/accept the runtime license and click Prepare, select the reviewed 4B Q4
starter and accept its model license/download, then open Chat and send the first
question. They attach to the already-running browser without changing its URL,
injecting JavaScript or submitting API writes. Read-only API observations verify
exact profile/manifest, the pinned model, ordinary successful Runs and a nonempty
answer. Separate XCTest results preserve the failing stage; the component UI
operation compiles these classes but deliberately does not execute them.

These newly added actions still require actual Mac execution; local Python checks
do not prove browser accessibility or Swift compilation. Stop/restart and a later
answer still use the existing API path. `consumer_gui_qualified` remains false:
complete streaming/Stop, update, backup, restore and removal acceptance is required
before consumer admission. Do not substitute partial coverage for that journey.

[First actual GUI run 41555762552](https://github.com/jahu/ai-station/actions/runs/41555762552)
built the complete package and passed the native setup-button assertion/click.
It failed while waiting for the default browser to become foreground; application
readiness was not observed, and no account/SDK/model qualification follows. The
precise startup cause is still unproven. GUI launcher exceptions now emit bounded
exception/traceback coordinates before displaying their normal error dialog,
without logging exception messages, account data or setup URLs. The experiment
also records only which fixed startup files exist before cleanup. These changes
make the next fault inspectable; they are not a claimed fix for that startup.

[Console run 41560567049](https://github.com/jahu/ai-station/actions/runs/41560567049)
also reached the 300-second whole-startup observation limit, with its configuration
and private desktop log present but no readiness record. It did not reach account
or SDK preparation. That limit is shorter than the permitted sequential bridge
and API-readiness operations (180 seconds each), before package retention and
database preparation are counted. The QA budget now covers that aggregate path;
the application's own operation deadlines and failure assertions are unchanged.
The browser assertion includes the preceding native installation time as well.

The launcher emits only fixed startup phase codes alongside its existing visible
progress. QA publishes phase changes and reads only the fresh owned Compose
project's fixed service state/health/exit/OOM fields before cleanup. It never
publishes container environments, health logs or raw errors. An SDK failure can
also record only the pinned public archive's native metadata and hash result,
without following a cache symlink or modifying/adopting the object. These are
diagnostic observations, not a waiver or evidence that the earlier failures are
fixed. Inspect the next actual runs before making a startup/model claim.

[Console run 41569774253](https://github.com/jahu/ai-station/actions/runs/41569774253)
at `88861ef` subsequently completed the real installed CPU backend scenario:
first administrator, native SDK preparation, the pinned 4B download, first model
answer, Stop/restart with identical saved conversation, a new model answer and
clean application Stop all passed. Its retained result has `passed: true`; the
overall Actions job is nevertheless **canceled**, not green. The former 45-minute
job ceiling interrupted the separate owned Docker Desktop shutdown after the
scenario finished in minute 44. The whole-job ceiling is now 60 minutes, including
that required cleanup; product operation deadlines are unchanged. This is useful
backend evidence, not a successful complete job or guided consumer admission.
The separate native/browser attempt and update/export/restore/removal gates remain.

[Native GUI run 41572578494](https://github.com/jahu/ai-station/actions/runs/41572578494)
at `f52afdc` failed before browser readiness. Its new child evidence reached
`preparing_browser_entry`: service startup and the first API check had completed,
but the private entry handoff did not. The parent reached its 180-second readiness
deadline; the later owned Docker inspection also timed out, and cleanup remains
uncertain. This does not establish why that Docker connection stopped responding.
The fixed bootstrap console call now disables Compose's default interactive mode,
uses EOF stdin and has its own 30-second deadline; subprocess timeouts retain safe
structured fault coordinates. A real neutral child test holds inherited input
open and verifies that the handoff still sees EOF and exits. See
[Docker's scripted exec guidance](https://docs.docker.com/reference/cli/docker/compose/exec/).
Actual guided execution must verify this correction before any GUI success claim.

Run [41575839010](https://github.com/jahu/ai-station/actions/runs/41575839010)
at `d000d9c` instead failed at native Runner health startup (`launch.py:338`),
before Compose services. The cause is not established by that deadline alone.
The native application now declares its ongoing supervision as user-initiated
activity and gives its owned NSTasks corresponding QoS, following
[Apple's app-level work guidance](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/PrioritizeWorkAtTheAppLevel.html).
Normal idle system sleep remains allowed; this changes no OS policy, entitlement
or Docker setting. This corrects the app's work declaration; App Nap is still an
unproven explanation for the earlier failures. Actual GUI qualification is required.

The previously qualified baseline retained a Linux-only consumer prerequisite gate. Independent
Darwin kernel ownership, peer credentials, telemetry, native Python and installed
Runner components have passed the platform checks below. Consumer .app packaging,
the Docker Desktop bridge and model setup/catalog are still separate requirements.
Removing the launcher's platform check alone cannot produce a correct Mac package.

The owner-dispatched native checks also compile a fixed Hypervisor-framework
prerequisite probe on each standard free Mac host. It is ad-hoc signed with only
Apple's required `com.apple.security.hypervisor` entitlement, runs as an ordinary
user, and creates/destroys one empty owned VM without a guest, vCPU or disks.
It reports raw create/destroy results and optional kernel observations; failed
compilation, signing, execution or destruction remains a failed check. A refused
VM creation records unavailable virtualization on that host, not a passing Docker
test or a claim about all Macs. No Docker software, license acceptance, OS settings
or paid runner is involved. This diagnostic binary is not shipped in the app and
its ad-hoc signature does not satisfy consumer signing/notarization.
[Required Apple entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.hypervisor).
GitHub explicitly documents missing nested virtualization on its ARM hosts;
Intel is observed separately rather than inferred from ARM.
[Hosted runner limitations](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#limitations-for-arm64-macos-runners).

The actual [2026-11-02 native run](https://github.com/jahu/ai-station/actions/runs/41420278249)
compiled, signed and executed this probe on both architectures. Intel macOS
15.7.9 created and destroyed its empty VM (both return codes zero); ARM macOS
15.8.2 refused creation (raw return code 4209590287; no VM existed to destroy).
Both report an outer VMM. Therefore an Intel Docker Desktop experiment is the
next available test, while the observed ARM host cannot supply this prerequisite.
Neither observation verifies Docker Desktop, shared native sockets, first-run,
Metal or the consumer installer. Do not generalize either result to every host
with that architecture.

The separate explicit `macos-desktop-transport` developer workflow uses only the
standard free public Intel host. It refuses an existing Docker app/configuration
before changes, verifies Docker Desktop 4.97.0 build 244584 against the publisher's
Intel DMG checksum and verifies its application signature. Docker's documented
administrator installer/license action is confined to that new disposable QA VM;
this never runs on an existing user's station or in ordinary native checks.
The desktop is started/stopped through its fixed CLI, then the existing private
socket/artifact/WAL probe tests a new chosen folder including Unicode and commas.
The only container download is the probe's pinned Python fixture; there is no AI
model, cloud credential, public listener or change to the consumer platform gate.
Failures remain failures with an owned probe receipt when available. Full Mac
installation, first result, updates/removal, Metal and signing require their own
evidence even if this narrower bridge experiment succeeds.
[Publisher release/checksum](https://docs.docker.com/desktop/release-notes/#4970),
[documented prerequisite installation](https://docs.docker.com/desktop/setup/install/mac-install/#install-from-the-command-line),
[bounded desktop start](https://docs.docker.com/reference/cli/docker/desktop/start/)
and [stop](https://docs.docker.com/reference/cli/docker/desktop/stop/).

`macos_desktop_docker.py` supplies read-only prerequisite discovery for a Finder
launch: it locates the installed Docker Desktop CLI in the system/user
Applications bundle, accepts only an executable inside that bundle, and reads
the fixed `desktop-linux` context in a minimal environment. Another station's
Docker/provider variables cannot redirect it. The resulting native Unix endpoint
is frozen for the probe's commands; no global context, settings, license, service
or software installation is changed. These helpers ship in the Mac application
resources, while the consumer prerequisite gate remains closed pending actual
transport and first-run acceptance.
[Docker's default CLI locations and user permissions](https://docs.docker.com/desktop/setup/install/mac-permission-requirements/).

The shared desktop importer and foreground supervisor now consume that discovery
through `desktop_engine.py`. Mac image inspect/load/reinspection, Compose startup,
first-admin console and data-preserving shutdown all use the selected absolute
CLI and explicit `--host` Unix endpoint. Docker context/TLS/config and remote
builder environment overrides are removed. The parent passes both coordinates;
the child independently re-discovers them and refuses a changed connection before
an engine operation. Linux/WSL retain their existing Docker configuration.
Neutral executable fixtures exercise real child processes and failure cleanup;
these checks do not qualify a Docker Desktop VM, native socket sharing or a
complete Mac installation. The consumer prerequisite gate remains in place.
The next startup stage uses the verified bundled application image itself for
the socket/artifact/WAL experiment, without downloading a separate QA image.
It tests a new disposable child on the configured data filesystem. An owned
isolated child permits Stop; a private pending marker blocks replay when cleanup
cannot be confirmed. This stage must pass before starting Compose and does not
replace actual native consumer qualification or remove the existing platform gate.
The supervisor explicitly imports helpers from its own bundled scripts under
isolated Python. The native bundle experiment also starts the actual installed
supervisor with `-IB --help`, without Docker or station-data creation, to check
this entry boundary independently of the `.app` manifest check.

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
Linux-only consumer prerequisite gate.

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

The developer producer `scripts/build_macos_package.py` assembles a real `.app`
layout around those components. It requires clean reviewed source, the exact
installed application Python inventory, a matching compiled native interface,
and a matching Linux control-plane image/build receipt for ARM or Intel. It
creates only a fresh desktop image tag and output; existing tags/apps are never
replaced. The native entry lives in `Contents/MacOS`, resources carry a checked
desktop manifest, and `Info.plist` declares architecture and minimum OS. The
Mac desktop/supervisor/Runner Python launches disable bytecode writes. This
producer does not start Docker Desktop, install prerequisites or activate Mac
consumer/model capabilities. Its output explicitly remains unsigned,
unnotarized and unqualified for consumer distribution.

Developer assembly, after producing all inputs at the same clean Git head:

```bash
.venv/bin/python scripts/build_macos_package.py \
  --architecture arm64 \
  --python-layer /absolute/path/application-python \
  --native-interface /absolute/path/native-interface \
  --image ai-station:reviewed-arm64 \
  --image-build /absolute/path/control-plane-build/build.json \
  --output '/absolute/new/path/AI Station.app'
```

The explicit native `macos_bundle_probe.py` exercises this producer and actual
`.app` executable with the real installed interpreter and a **neutral image
provider fixture**. It checks resource verification, tamper rejection,
conflicting CLI flags, unchanged interpreter inventory and no account/data
creation. Its fixed image bytes are never loaded or called a working control
plane. Docker Desktop transport, Finder/first-run UX, model setup/inference,
updates/removal and Gatekeeper/signing remain the independent acceptance gates
below. This experiment runs only in the owner-dispatched native checks.

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
   The developer probe accepts `--data-directory` for the chosen existing app
   folder. It creates and mounts only a new private disposable child there,
   keeping its native socket/client configuration under a separate short path.
   Existing databases/artifacts are neither mounted nor opened. Probe receipts
   retain both owned roots when container cleanup is uncertain; successful
   cleanup checks original device/inode/UID/mode before removing either root.
   Symlink traversal and shared-writable data folders fail before probe writes.
   A successful `/tmp` test alone does not qualify the chosen data filesystem.
   Mount fields use CSV encoding so commas/quotes in a selected folder cannot
   become extra Docker options or redirect its source.
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
   The [managed native SDK contract](macos-managed-llama.md) connects the existing
   verified binaries to ordinary setup Runs and private/opaque activation receipts.
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

### Offline database upgrade transaction

The separate [private desktop backup contract](desktop-snapshots.md) records the
implemented full-export/restore coordinators and remaining native UI/actual Mac
acceptance. A database-only export or a host-folder copy is insufficient.

Implement the data transaction before wiring native update consent. A fixed,
trusted installer command in the verified control-plane image uses its existing
Alembic revisions with an explicitly supplied staging connection. The native
Runner does not acquire SQLAlchemy, migration or database ownership. This is an
offline installer operation, with no HTTP/agent entry point or arbitrary command.
Custom database URL overrides are refused rather than backing up another file.

Bind an operation UUID to previous/target bundle identities and the original
database/WAL fingerprints. Hold the existing launcher and migration locks; a
durable data-root marker blocks normal API/supervisor startup until publication
or safe abort. Keep a verified standalone SQLite backup, migrate a separate copy,
and check integrity/foreign keys before publishing. Preserve accounts, passwords,
sessions, schedules, run history and every existing file; do not invoke restore's
deliberate session/schedule normalization. Keep original configuration and models.

Publication verifies that source bytes still match, records its intention before
handling old SQLite sidecars, and atomically replaces only the database. An exact
operation may resume an interrupted publication; changed input or unexpected
writes require inspection. Abort before publication leaves the original database
and all backups intact. Never silently roll back after the new version has made
writes. The later native coordinator must verify the retained owner, obtain
explicit update consent and confirm owned services are stopped before dispatch.
Actual Docker Desktop acceptance must also prove native/container visibility of
the launcher locks; Linux-only flock tests do not qualify that Mac boundary.
This transaction alone does not enable the Mac consumer prerequisite gate or
qualify Finder/update/removal, Docker Desktop, Metal or signing.

### Version identity and native ownership

A separate same-OS-user `identity` query on the private desktop control channel
preserves the existing status/Stop wire formats. It returns only the verified
package's bundle/image identities, bounded version and
source epoch, tied to the current desktop instance; never a PID, command, setup
link, prompt or credential. Owners without this capability cannot be assumed
safe update targets.

Keep a private version receipt outside mounted app data. Bind it to the canonical
data directory and its filesystem identity, Compose project, accounts profile
and Runner socket path. Record `starting` before launch and mark `ready` only
after the existing matching-instance API readiness check. A retry of the same
verified package is allowed; changed storage/package or untracked existing data
requires inspection/explicit upgrade rather than silent migration. Ephemeral
socket directories may be recreated after reboot without changing installation
identity. Model endpoint/worker-count changes do not relocate the installation.

The later updater must attest status, identity and ready receipt together before
instance-bound Stop, then use the offline image transaction and controlled
version activation. These primitives do not offer an unbacked Update button or
remove the consumer gate; actual Mac/Docker Desktop and preserving-update
qualification remain required.

### Consented native owner handoff

The internal installer handoff serializes update attempts with a separate private
lock. It requires the live owner's ready package/storage receipt and held native
desktop lock before presenting a local consent callback with safe version
metadata. Recheck the same owner, storage and lock inodes after consent, then
send Stop bound to that instance. A bounded wait never force-kills or substitutes
a replacement owner. Hold the native desktop lock through the updater's context;
replaced locks, changed storage or an older package require inspection.

This primitive stops only the native owner. It does not assert that Docker
services exited successfully, dispatch a migration, activate another version or
offer an Update button. The next coordinator must inspect the exact owned
Compose containers before dispatching the fixed offline image transaction and
durably coordinating its result with version activation. Actual Docker Desktop
and complete preserving-update qualification remain required.

## Acceptance evidence

### Native update entry point

The running native launcher offers a local application-bundle chooser. Its
existing verified Python validates the downloaded bundle's architecture, minimum
OS, manifest and inventory, then copies an immutable retained payload. Import
and disposable bridge checks use the current trusted installer before presenting
the version-change/Stop consent. Cancel keeps the running owner. Accepted updates
reuse the native handoff and fixed image transaction; they never replace a live
checkout or unrelated application files.

The native parent tracks the updater as its own child and adopts it as the new
supervisor after the old owner exits. Quit signals only those owned tasks. The
minimal original application bundle remains a bootstrap: cold launches verify
the active private receipt and retained payload before executing its interpreter.
The web application/runtime payload updates without rewriting `/Applications`
or requiring administrator access. Bootstrap bundle replacement/signing remains
part of complete distribution qualification, not an implicit filesystem action.

A dispatch fence on cold launch offers to continue the exact retained operation;
it cannot start the previous application against uncertain data. Reconstruct the
same engine/namespace/request, inspect its existing command and only publish a
confirmed prepared transaction. A confirmed abort returns to the previous
payload. Uncertain starts or failed partial publication require inspection rather
than automatic retries or data rollback. No setup token enters native UI frames.
These candidate routes preserve the Mac consumer prerequisite gate until real
Docker Desktop and complete first-run/update/removal qualification is available.

### Fixed image dispatch and activation contract

After the consented native handoff, require an empty inventory for the exact
configured Compose project. Do not stop or adopt unknown containers. Freeze the
local Docker connection, namespace, previous/target packages and operation UUID
in private installer storage outside mounted data. Dispatch only the verified
target image's `app.desktop_upgrade` prepare/publish/abort/status commands, with
network disabled, no GPU/socket access, one data mount, non-root UID/GID, bounded
CPU/RAM/pids and a read-only root filesystem. Never inherit a shell command or
host environment as workload configuration.

Journal container identity and command intent before creation/start. Inspect
identity, labels, image, command and isolation before waiting, collecting output
or stopping that exact container. A lost acknowledgement is inspected against
the original container; never restart a command that may already have executed.
Retain original/staged database files and private outcomes on failure. Remove
only confirmed owned containers; uncertain creation or cleanup stays fenced.

A separate data-root dispatch fence blocks API/supervisor startup before Docker
receives a request, including the gap before SQLite preparation creates its own
transaction fence. On successful publication, atomically activate the target's
`starting` version receipt before removing the dispatch fence. An acknowledged
abort preserves the previous receipt. A retry after completed activation reports
its retained outcome without reverting a newer owner or replaying migration.
This is internal installer infrastructure, not an Update button or qualification
of the full Mac Docker Desktop/consumer journey.

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
