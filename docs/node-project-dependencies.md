# Node projects in owned coding worktrees

Extend the existing explicit dependency-install Run and sandboxed project checks
to JavaScript/TypeScript projects. Python projects keep their existing behavior.
HTTP accepts the owned worktree and project revision, never npm arguments, registry
URLs or host runtime paths. Native configuration selects an existing Node/npm
runtime; absence is reported without modifying the operating system.

For a Node-only project, read a bounded regular package.json and package-lock.json
inside the allocated worktree. Validate package declarations and every lockfile
download against the public npm registry, reject VCS/URL/file dependencies and
project .npmrc overrides, and disable all lifecycle scripts. npm ci runs in the
existing native sandbox with scratch HOME/cache, no credentials, immutable Git
metadata and owned-group cancellation/time/output bounds. The report retains
manifest hashes, packages, exit status and runtime version. Uncertain execution
is inspected rather than repeated.

Existing npm v3 lockfiles are checked and never regenerated. When no lockfile
exists, a bounded native resolver stages a copy of package.json in the owned
scratch directory. It repeatedly runs npm's lock-only resolver with **network
disabled**. A typed registry client fetches only canonical package metadata from
registry.npmjs.org, pins a checked public IP while preserving TLS authority,
refuses redirects and limits response/aggregate size. Only versions with checked
public tarballs, SHA-512 integrity and safe installed dependency declarations enter
the cache. Uninstalled development dependencies and package scripts are omitted
from that metadata; root development dependencies are still reviewed and installed.

Cache seeding is fixed adapter code and also runs with no network. Incomplete
optional dependency metadata must be fetched before resolution is accepted; npm
otherwise silently drops missing platform packages while reporting success.
Intermediate locks stay inside this Run's staging directory. The complete lock
passes the same source/integrity checks as an existing lock, then is created
exclusively in the worktree, preserving any file created concurrently. Only then
can ordinary npm ci execute. Metadata names, hashes, sizes and excluded-version
counts are retained in the dependency report. The UI identifies generated locks.

Resolution and installation share one deadline, process group, Stop and output
bounds. Limits are 200 metadata packages, 8 MiB per response and 48 MiB total.
Existing .npmrc, npm-shrinkwrap, workspaces and URL/Git/local sources remain
unsupported. Offline resolution cannot contact transitive sources, run lifecycle
scripts or gain network permissions. New lockfiles are inspectable project files;
uncertain native execution is never automatically replayed. Trusted build/test argv
still runs inside the network-disabled validation sandbox.

Normal tests use fake runtimes and temporary repositories. An opt-in real Node/npm
check qualifies dependency installation and build in a disposable owned worktree;
no unrelated Node installations, repositories or model runtimes are modified.

## Setup and qualification

Configure `AI_STATION_NODE_PREFIX` to a standard existing Node 22+ distribution
containing `bin/node` and `lib/node_modules/npm/bin/npm-cli.js`, then restart
the native Host Runner. Diagnostics reports the configured runtime. Optionally
install an isolated project-local distribution explicitly:

```bash
.venv/bin/python scripts/install-node-runtime.py
# Copy the printed AI_STATION_NODE_PREFIX into .env and restart AI Station.
```

The installer verifies the official Node archive SHA-256 and never overwrites
an existing installation or changes system Node. Runtime files remain read-only
in coding sandboxes. Owned child processes receive EOF through a closed input
pipe: the sandbox denies fstat of an inherited host /dev/null descriptor, which
causes Node 22 to abort before JavaScript starts. Commands remain non-interactive.
Node receives the system OpenSSL configuration read-only, and DNS uses the host
resolver over TCP within the owned process; no host DNS configuration changes.

On 2026-10-15, an opt-in disposable-repository check installed the actual public
`is-number@7.0.0` package with Node 22.23.3/npm 10.9.9, then ran a configured npm
build. It verified the dependency worked, preinstall did not run, outside-worktree
reads and Git metadata writes were denied, and the original checkout/index were
unchanged. Evidence: `data/acceptance/node-project-dependencies-20261015/real-result.json`.
Normal automated tests use fake runtimes and no npm downloads.

The lock-generation increment additionally passed an actual no-lock installation
of `is-odd` and its transitive `is-number` dependency, followed by a sandboxed build
and the same file/Git/lifecycle checks. Evidence:
`data/acceptance/node-lock-generation-20261015/real-result.json`.

The final-source real React 19/Vite 7 check started without a lockfile, resolved
platform/optional dependencies, installed the checked inventory with lifecycle
scripts disabled and completed Vite's production build. It also passed outside
read/Git write denial and original-checkout/index preservation. Evidence:
`data/acceptance/node-lock-generation-20261015/real-react-result.json`. This
qualifies that actual frontend build, not a claim that a coding model created it.
