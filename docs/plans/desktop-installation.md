# Desktop installation

NR-13 remains required on Linux, Windows and macOS. The first packaging
increment targets Linux x86-64; it does not establish the other platforms.
Preserve the existing Docker control plane and native Runner. First launch
must reach the account setup proof and guided runtime/model flow already
qualified in PRs #530–#532.

## Packaging decision

Bundle a checksum-pinned, relocatable CPython distribution and pinned native
Runner dependencies. Native operations use `sys.executable` both for journaled
children and ordinary `venv` creation. Replacing that interpreter with a frozen
application executable would change their contract; keep a real Python instead.
Consumers do not install Python, pip, Node or developer dependencies themselves.

The initial Linux desktop shell uses the installed Zenity dialog service and
the existing browser UI. It is a local installation/supervision process, not
a new HTTP backend, Run engine or unrestricted host service. Future desktop
shells can reuse the same packaged interpreter and supervisor on other OSes.

The build creates a versioned application directory and Debian package with
a desktop entry. It carries the compiled control-plane image, exact image ID
and archive checksum; it never builds the frontend on the user's computer.
Only this fixed image archive may be imported. The private search image remains
the existing pinned Compose dependency. Package contents include dependency
license notices. No weights, credentials or personal data enter a package.

## Install and startup

1. The user opens the installed desktop entry. Show prerequisites and local
   storage/network use. Docker/Compose must be installed and available to that
   user. Explain missing prerequisites through the desktop, not a traceback;
   never install drivers or change daemon/group/OS settings silently.
2. After local confirmation, create private XDG application storage. Copy the
   shipped bundle into an immutable versioned application directory there,
   so an OS package update cannot remove code from a running generation.
   Preserve existing version directories and user data across upgrades.
3. Create configuration only for a new owned desktop installation: accounts,
   loopback HTTP, a dedicated Compose project/image and data root. Existing
   operator installations are not silently migrated or adopted. Occupied ports
   must not trigger another application's shutdown.
4. Import the verified bundled image if its exact identity is absent; launch
   the existing foreground supervisor with the explicit configuration. Its
   account proof is passed to the browser without appearing in ordinary logs.
5. Open the existing app at account setup or Chat. Offer model setup afterward.
   Closing a browser does not cancel Runs; stopping the desktop station signals
   only its own supervisor and uses its existing data-preserving shutdown.
6. Opening the desktop entry again reuses the live desktop owner's browser link.
   It neither prepares another image nor starts/restarts services. While the
   first instance is preparing, explain that its existing progress window owns
   startup. A newly acquired desktop lock discards stale readiness before work;
   ordinary shutdown and failed startup remove the current link.

The readiness handoff is an atomic mode-0600 file in the owned desktop state
directory, read only after observing the existing desktop lock held. It can
contain the one-use first-admin setup link, so it is not a log or HTTP resource.
Reads reject symlinks, hard links, nonregular or shared-readable files and
unexpected URLs. Only the existing loopback browser/setup destinations are
accepted. Opening an updated package while the previous desktop owner is active
opens that running version; it does not apply an update during its jobs.

## Qualification and remaining work

The next desktop increment keeps the existing supervisor alive when the native
status window is closed or **Run in background** is chosen. **Stop AI Station**
is a separate explicit action. Reopening the entry opens the browser and can
show controls for that background owner. A private, same-OS-user Unix socket
supports only status and instance-bound stop; it is outside the mounted data
root, carries no setup token, and accepts no process IDs, commands or URLs.
Only the owning supervisor signals the child it launched. Long socket paths
reuse the qualified directory-descriptor transport. Terminal status/stop flags
support diagnostics and qualification without adding application HTTP routes.
This is session background supervision, not login autostart or reboot recovery.

Qualification must exercise background/close/open/stop with an actual packaged
supervisor and independent clients, reject stale-instance stop and unsafe socket
files/peers, prove no duplicate services or unrelated process signals, and retain
account/history across a later restart. Native dialog rendering and button
semantics require a real private GUI experiment in addition to fake tests.

Unit tests must cover configuration isolation, import identity, no overwrite,
owned shutdown, occupied ports and setup-link handling. Build the actual bundle,
relocate it, test Python/SSL/venv/native readiness without host Python/Node,
and run an isolated app with the packaged image and real account onboarding.
Then verify retained state through restart/update/uninstall. Synthetic runs
prove packaging/lifecycle; real model first-result evidence stays separate.

A GUI shown on this workstation is not clean-machine acceptance. Actual
prerequisite acquisition, supported Linux distributions, Windows WSL2/Docker
transport and macOS native CPU/Metal execution still require their advertised
platform journeys. Package signing/public release follows the owner-controlled
release policy; development artifacts stay private until reviewed.

## Build and current qualification

Build from a clean reviewed checkout with Docker, `uv` and `dpkg-deb`:

```bash
python3 scripts/build_linux_package.py --output /path/to/new/ai-station-linux --deb
```

The builder refuses existing output and dirty sources. `--allow-dirty` is only
for private experiments. It includes only an explicit source allowlist, a normal
native wheel, checked Python and hash-pinned runtime dependencies; developer
credentials, `.env`, application data, model weights and test artifacts are not
included. The pinned CPython 3.12.14 source/hash is taken from
[Astral's versioned download metadata](https://github.com/astral-sh/uv/blob/0.12.16/crates/uv-python/download-metadata.json).
The installed package has a desktop entry; its private version copies and data
are independent of OS package replacement/removal. No package hook deletes data
or changes Docker, driver or account permissions.

A real first-start experiment found that the normal desktop data directory
could exceed the Unix-domain socket address limit for llama.cpp. Linux now uses
an open parent-directory descriptor as the short bind/connect address when
needed; socket files stay inside their original validated owned directories.
No global symlink, TCP listener, filesystem relocation or changed native request
identity is introduced. Descriptors close after bind/connect, including errors
and cancellation; streaming uses the already-connected socket. The same helper
covers the native Runner listener and supervisor health probe.

The initial actual bundle is relocatable and creates a real nested Python venv
without system Python packages. A clean-source Debian payload was extracted into an isolated staging directory,
then its actual Zenity dialogs ran on a private authenticated X server. It
created the first administrator in the compiled browser UI, opened guided model
setup, verified/adopted the existing public Q4 weights and returned a real GPU
reply. Desktop/mobile rendering, scoped model Stop, full desktop Stop, restart
with the same cookie/account/memory/history/model registry, and a separate
packaged fake worker all passed. Both Runner and model socket paths exceeded the
usual address limit. No new weight download, production mutation or real OS
package installation is claimed. Private evidence is under
`data/acceptance/linux-desktop-package-20261031/`.

The complete native suite passes 1248 tests (two opt-in skips); the eight complete
backend/launcher/recovery families pass 129 cases, with 69 final socket/transport
cases. Full Python lint/format covers 825 files. Two old recovery assertions were
updated from schema 0041 to the existing 0042 migration; no migration was added
or bypassed. The desktop package and Docker image were built from clean sources.
QA v21 adds INSTALL-101 without changing issued workbook answers. These checks
are the documented focused local equivalent; final source/package/Compose review
and preserving deployment remain separate. Building and testing this `.deb`
does not complete clean-machine NR-13 or qualify Windows/macOS.

A second actual two-version exercise removed the staged OS package payload
while the old private interpreter/supervisor kept running, stopped that owned
station, then extracted and started the newer package. The same account cookie,
memory and successful Run history survived; workers executed before and after,
and both immutable code versions plus configuration were retained. This is
payload-removal/reinstallation qualification without OS mutation, not a claim
that apt installation/uninstallation or a clean machine has been exercised.

Desktop preparation uses a small native progress window. After readiness,
closing the status window or choosing **Run in background** leaves supervision
active in the current user session. Reopen the desktop icon to access the same
browser and background controls; **Stop AI Station** explicitly closes only
that installation. Terminal diagnostics use `station --status` and
`station --stop`; `--background` skips the status window while retaining the
owning launcher process. Login autostart/reboot recovery, a tray, prerequisite
acquisition, signing/distribution and actual cross-platform installations remain
consumer-setup work.
