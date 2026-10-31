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

## Qualification and remaining work

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
without system Python packages. Full GUI/account/model/first-result/restart
qualification remains a gate until its exact evidence is recorded; building a
`.deb` alone does not complete NR-13 or qualify Windows/macOS.
