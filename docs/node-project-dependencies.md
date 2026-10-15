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

Managed installs require an existing npm version 3 lockfile. Generating a lock
through npm itself is not enabled: transitive Git/URL dependencies could otherwise
be contacted before the resulting lock is checked. Project npm-shrinkwrap files
are also refused because they override package-lock.json. A future controlled
registry resolver may generate locks without that exposure. No postinstall hook
or extra arbitrary shell operation is introduced. Trusted configured build/test argv
use the selected Node runtime in the existing network-disabled validation sandbox.

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
