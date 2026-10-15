# Full validation for AI Station self-development

Observed on the deployed `35ab4a4` release: the registered AI Station project has
only two `compileall` commands, no lint/build commands. Read-only automatic
planning of this repository returns no commands or dependency ecosystems. The
root pyproject contains tool settings, while pytest tests and the Node package
live below it; requirements-dev.lock is outside current manifest selection.
Evidence: `data/acceptance/self-development-validation-20261015/observed.json`.

This is not a failed real self-development feature task. It is a verified gap in
the checks that such a task would receive. The earlier documentation-only smoke
proved worktree isolation and syntax checks, not full application validation.

Implement a reviewed, frozen project validation configuration that can represent
component directories, development dependencies, Python source roots and sufficient
validation time. Preserve existing simple-project requests and manifest snapshots.
Start by inspecting existing manifest/dependency/sandbox contracts; extend them
instead of introducing a parallel self-development execution architecture.

AI Station's profile must run backend/Runner pytest and Python lint/format, plus
frontend lint, TypeScript, tests and production build against the allocated
worktree. Runtime/dependency preparation must be explicit and inspectable. Never
fall back to importing the active checkout's editable packages, and never mount
the Docker socket or grant arbitrary host command/filesystem access.

All component/source/manifest paths must be canonical relative worktree paths,
with symlink/escape protection and frozen hashes before execution. Agents cannot
rewrite trusted validation configuration mid-task. Preserve owned process groups,
Task Stop, deadlines, conservative recovery, reports, diffs and review. Consider
short owned temporary paths for tests that create Unix sockets without granting
general host temporary-directory access.

Use disposable repositories/fakes for policy, snapshot, import-source, timeout,
cancellation and legacy compatibility tests. Then execute full validation in an
isolated AI Station worktree and prove it uses changed worktree source. Preserve
the original checkout/index and all user data. No merge/restart of the application
is implied by a successful self-development task; deployment remains separately
controlled. Do not mark the whole platform complete from this one increment.

## Component environment increment

Projects gain an optional advanced `validation_environment` (migration 0026):
`python_manifest`, `node_directory`, `python_source_roots`, and a bounded
`timeout_seconds` (60–7200, default 900). Select a root Python manifest explicitly
when preparing both Python and a nested Node component. No arbitrary environment
variables, shell strings, absolute paths, path aliases or host grants are accepted.
Ordinary projects retain their existing detection and request/snapshot shapes.

The existing read-only preparation Run snapshots the selected Python manifest and
separate Node package manifests. Existing dependency Runs install selected Python
requirements into the worktree venv and Node requirements in the configured
component, using the existing public registry restrictions and disabled npm
lifecycle scripts. Component installs reject ancestor npm configuration. Python's
installer uses isolated module resolution (`-I`) so project `pip.py` cannot run as
the installer. Scratch stays under the owned worktree and remains excluded from
proposal review by the existing reserved-directory rules.

Validation records the frozen environment and both snapshots. It checks hashes
again before executing, sets Python source roots to this worktree, and uses the
chosen job/command time limit. Manual worktree actions inspect and freeze manifests
in their worker before dispatch; HTTP handlers only enqueue. Repeat checks retain
recorded configuration and snapshots, without model inference or dependency setup.
Editing project settings cannot change an active Run's configuration.

This increment does **not** qualify the entire AI Station suite inside the native
sandbox. A disposable installed-Cursor-sandbox probe confirmed that reading the
host boot identity and enumerating `/proc` is denied; owned process tests need
those observations. Unix socket creation inside the owned worktree is available.
Do not grant host `/proc`, home or broad temporary-directory access to pass these
tests. The next increment needs a controlled container validation target with its
own process namespace and private temporary storage, behind the native Runner.
Only that subsequent real full-suite execution can close self-development
validation acceptance. The registered production Self project remains unchanged.


A disposable real native-sandbox smoke passed selected development-lock offline
wheel installation, nested real Node/npm installation and build, and Python import
from the allocated source folder. Its original repository HEAD, index and checkout
were preserved. The first attempts exposed the isolated installer's need to read
exact public OS/MIME metadata files; those failures are preserved alongside the
successful rerun in local acceptance evidence. This is component execution
qualification, not the full AI Station self-suite.


Local release qualification for PR #323: 1597 backend/Runner tests passed with
five opt-in skips; 489 UI tests and frontend format/lint/typecheck/build passed.
Both Compose configurations and the application image built successfully. A
0025→0026 migration and downgrade/upgrade round trip preserved an existing project
in a disposable database. The compiled advanced settings saved and restored the
component configuration at 1440, 390 and 320 pixels without horizontal overflow.
Real native acceptance covered both an existing npm lock and generation of a
missing component lock; no external AI, user repository or GPU workload was used.
Deployment identity and backups remain recorded in the central local release
record, separately from this validation evidence.
