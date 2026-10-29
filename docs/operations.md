# Packaging, upgrade and recovery

The control plane remains a Docker Compose project plus a native Host Runner. Startup, shutdown and image builds stay on the host through `./scripts/start.sh`. The API does not start, stop or retag containers, and it does not restore a database over the live file.

## Data that must survive shutdown

Application data lives on a host bind mount (`AI_STATION_DATA_HOST_PATH`, default `./data`) mapped to `/data`. It is not a named Docker volume. `docker compose down` removes containers and the Compose network. The launcher calls `compose down --timeout 10` and never passes `--volumes`, `-v` or `--rmi`. Even `compose down --volumes` would not delete bind-mounted host files; do not pass that flag anyway, and do not convert `/data` into a named volume.

Ctrl+C on the owned supervisor stops only that deployment's containers and, if this process started the Host Runner, that runner. It does not take over a pre-existing Compose project and does not delete SQLite, artifacts, backups, worktrees or Library files.

## Honest upgrade path

1. Confirm there are no Runs you still need to finish. System reports `active_runs`. Interrupted work stays inspectable; recovery never blindly repeats uncertain side effects.
2. From **Settings → Maintenance → Backup and upgrade readiness**, queue **Back up SQLite**. Wait for the Run to succeed and keep the integrity-checked copy under `backups/<run-id>.sqlite`. **Inspect copy** re-checks that file in place; applying it over the live database stays unpublished in-app.
3. Stop the owned supervisor (Ctrl+C) or `docker compose down` without `--volumes`.
4. For a normal release upgrade, check out the chosen published tag from `master` in an isolated checkout. A development preview may instead use a reviewed commit on `develop` in a new isolated worktree. Do not treat preview `:8765` as containing later PRs.
5. Rebuild the application image (`./scripts/start.sh`, or `--no-build` only when that image already contains the reviewed commit).
6. Alembic runs on API startup against the existing database. Migrations are additive. For a necessary database recovery, use the stopped-service procedure below; never copy over a live WAL database.
7. Open `http://127.0.0.1:8765` and confirm health. Existing conversations, Runs, artifacts and settings remain.

This path does not retag unrelated images, migrate other Docker projects, pull GGUFs, or apply a changed checkout automatically.

## Upgrade readiness

`GET /api/maintenance` reports the live Alembic revision versus code head, the application-owned SQLite path, WAL journal mode, active Run count, bind-mount persistence, and interrupted Runs that still need inspection. It is inspect-only. `restore` and `image_rollout` are `unpublished`. Private LAN access is allowed only with the operator password and an explicitly configured private address; its reported status uses the same policy as Operator access. Public binding remains refused. `GET /api/maintenance/backups/{run_id}` re-checks a successful copy without writing. `GET /api/maintenance/image` asks the Host Runner to compare the `ai-station:local` tag with running `ai-station`/`worker`/`scheduler` containers. It never builds, tags, starts, stops or retags. See [private access](private-network-access.md) for configured LAN and optional Tailscale HTTPS access.

## SQLite backup

`POST /api/maintenance/backups` enqueues a Task/Run (`station.backup`, executor `sqlite_backup`) with `manage_station` only. Agents do not receive that permission. After releasing the worker transaction, the executor copies the live SQLite file with `VACUUM INTO` into `backups/<run-id>.sqlite`, runs `PRAGMA integrity_check` on the copy, and stores that file plus a JSON report as artifacts. Cancellation is honored before the copy and before artifact registration; a canceled Run deletes a partial copy. Recovery never restores the copy and never retries the Run automatically (`retry_class=inspect`).

`GET /api/maintenance/backups` lists recent backup Runs and their stored artifacts. That list is one keyboard sequence (arrows, Home, End, Enter inspects the backup Run) with unique Inspect names; Inspect copy and Download copy stay on the selected row. System can download the SQLite copy through the ordinary artifact file endpoint. `GET /api/maintenance/backups/{run_id}` opens the stored copy read-only, repeats `PRAGMA integrity_check`, hashes the file, and reads its Alembic revision. A hash mismatch or failed integrity check is reported; the live database is not replaced. In-app restore remains unpublished because swapping SQLite while the control plane holds WAL connections is unsafe. After a successful unchanged re-check, the copy displays offline recovery instructions for the workstation.

## Offline database recovery

Recovery is a host administration command, separate from agent tools and HTTP
execution. Run it from the reviewed AI Station checkout with the **same data
configuration** as your deployment. An isolated checkout needs its own `.env`,
an explicit `AI_STATION_DATA_HOST_PATH`, or `--data-root /absolute/path/to/data`.
Relative configuration resolves from the checkout. Container `/data` is not the
host data directory.

1. Keep the complete original application data directory. A SQLite copy contains
   metadata, not artifact bytes, worktrees or model weights. In Settings →
   Maintenance, **Inspect copy** shows offline instructions only for a successful,
   unchanged, integrity-checked backup.
2. Inspect the intended UUID on the host. This default mode does not create files
   or alter the database:

   ```bash
   ./scripts/restore.sh --backup-run <backup-run-uuid>
   ```

   Review its SHA-256, source/target schema, missing artifact files, record counts,
   agents to pause and uncertain Runs. Missing original artifacts block apply.
   Compatible older copies migrate only on a private staging connection. An
   unknown/newer backup or current schema requires a compatible checkout.
3. Unload AI Station-owned models in Models, finish or stop its tasks, then use
   Ctrl+C in the owned supervisor terminal. A running launcher, containers mounting
   this data root (including owned model/preview containers), live native process
   groups, or open database users block apply. The recovery command inspects them;
   it does not kill processes or stop unrelated services.
4. Explicitly apply the exact digest reviewed in step 2:

   ```bash
   ./scripts/restore.sh --backup-run <backup-run-uuid> --apply --expected-sha256 <reviewed-sha256>
   ```

   The command preserves private raw original files under
   `recovery/<recovery-uuid>/`, and creates a standalone rollback copy under
   `backups/<recovery-uuid>.sqlite` when the original is structurally usable.
   A corrupt original is retained without claiming a usable rollback copy.
   It stages, migrates, normalizes and verifies the copy before atomic replacement.
   A private `receipt.json` records hashes, actions and the rollback ID. No
   credentials appear in the report; persistent paths remain data-relative.
5. Run `./scripts/start.sh`. Current operator credentials and login rate budget
   survive recovery. Device sessions and restored node invitation tokens are
   revoked. All agents stay paused, pending approvals are denied, nonterminal
   Runs become `interrupted` with inspection required, and obsolete worker/resource
   holds are released. No workload, schedule or external side effect replays.
   Re-enable only the definitions you reviewed; inspect interrupted history.

If the current credentials are unreadable, apply requires a **new** 12–200 character
operator password. Enter it twice at the terminal prompt, or supply a private
user-owned `--operator-password-file /path/to/private-file` (0600/0400). Do not put
passwords in command arguments or chat. Older backup credentials never silently
replace a readable current password.

### Interrupted recovery

A durable marker prevents ordinary startup from proceeding before a prepared
recovery is resolved. Use the same stopped-service conditions and data configuration:

```bash
./scripts/restore.sh --pending
./scripts/restore.sh --finish <recovery-uuid>
```

Finish accepts only the originally approved unchanged stage/current file and
receipt. It can finalize a swap that already happened, without replaying work.
Unknown or changed WAL files and changed receipts block it. To cancel preparation
**before replacement**, use `./scripts/restore.sh --abort <recovery-uuid>`; it keeps
the original database and removes only its verified owned staging file. Once the
swap happened, do not delete the pending marker or copy original files manually:
finish first, then explicitly inspect/apply the retained rollback UUID if needed.

Recovery qualification uses disposable databases and a loopback-only API, never
an experimental restore over the operator's production database. See
[the recovery contract](plans/offline-database-recovery.md).

## Interrupted work

Conservative recovery still parks uncertain dispatched work as `interrupted` after the owned process is gone. **Mark inspected** records that a person looked at the Run. It does not requeue, restore a backup, or replay side effects. Interrupted Runs are one keyboard sequence (arrows, Home, End, Enter inspects) with unique Inspect names; Mark inspected stays on the selected row. Home can Retry an interrupted Images Run as a new Run through the existing image retry endpoint without leaving Home or opening the inspector. Explicit retry, when a domain already supports it, remains a new Run. Audio and avatar retries stay unpublished. System lists currently held leases and expired-lease counts without offering replay; arrow keys move through that list and Enter inspects the Run. If no worker is available, those expired leases stay listed until a worker ticks.

## Compose image inspect

**Settings → Maintenance → Backup and upgrade readiness → Inspect running image** compares the current `ai-station:local` image ID with running control-plane containers that use that tag. Running containers are one keyboard sequence (arrows, Home, End) with unique Container names. A mismatch means the tag was rebuilt while those containers still run an older ID. Applying that tag, building from the UI, or taking over preview `:8765` stays unpublished. Rebuild from a reviewed checkout in an isolated worktree using `./scripts/start.sh`.

## What remains unpublished

- Applying a backup over the live database
- Building or rolling out `ai-station:local` from the UI
- Taking over a running preview deployment

Private LAN publishing is implemented separately by the launcher and Operator
access settings. It does not enable in-app restore, image rollout or public exposure.
## Recovering an API port after network startup

Docker may start before the workstation receives its configured private LAN
address. A failed port bind can leave an exited API, or an internally healthy
container without a host publish mapping. `./scripts/recover.sh` inspects that
specific failure and waits for the configured address and matching private Host
Runner. It recreates only the owned API with its existing immutable image.
Running workers, native processes, models, the database and other Docker projects
are preserved. A newly tagged image is never applied by recovery.

Recovery requires a local Docker Unix endpoint and validates the Compose project, exact checkout/config files, user,
data/socket mounts, hardening and intended loopback/private binds. An occupied
port, unknown deployment or partial mapping requires inspection. An absent
project, deliberately stopped API or existing foreground supervisor is left
alone. Created-but-never-started worker/scheduler containers may be started
after successful repair; running or deliberately stopped roles are preserved.
There is no recovery endpoint or agent tool. This is a local operator utility.

For recovery when your user session starts:

```bash
./scripts/recover.sh --install-user-service
systemctl --user status ai-station-recovery.service
```

This installs only AI Station's user unit, without sudo, driver changes or
enabling lingering. Existing unrelated units are never overwritten. It retries
after an unavailable network or Runner. The selected checkout and environment
file are fixed in that unit; rerun the installer when switching to another
checkout. An external environment file can be selected with `--env-file`.
Disable with `systemctl --user disable --now ai-station-recovery.service`.
Ordinary startup remains `./scripts/start.sh`.

The API's image pin is retained in `runtime/recovery/` with private permissions
so subsequent recovery can validate its Compose provenance. Normal explicit
upgrades use their own image policy. Recovery does not build, pull, upgrade,
restart the Host Runner, take over cleanup ownership or modify application rows.
