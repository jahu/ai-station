# Packaging, upgrade and recovery

The control plane remains a Docker Compose project plus a native Host Runner. Startup, shutdown and image builds stay on the host through `./scripts/start.sh`. The API does not start, stop or retag containers, and it does not restore a database over the live file.

## Data that must survive shutdown

Application data lives on a host bind mount (`AI_STATION_DATA_HOST_PATH`, default `./data`) mapped to `/data`. It is not a named Docker volume. `docker compose down` removes containers and the Compose network. The launcher calls `compose down --timeout 10` and never passes `--volumes`, `-v` or `--rmi`. Even `compose down --volumes` would not delete bind-mounted host files; do not pass that flag anyway, and do not convert `/data` into a named volume.

Ctrl+C on the owned supervisor stops only that deployment's containers and, if this process started the Host Runner, that runner. It does not take over a pre-existing Compose project and does not delete SQLite, artifacts, backups, worktrees or Library files.

## Honest upgrade path

1. Confirm there are no Runs you still need to finish. System reports `active_runs`. Interrupted work stays inspectable; recovery never blindly repeats uncertain side effects.
2. From **System → Backup and upgrade readiness**, queue **Back up SQLite**. Wait for the Run to succeed and keep the integrity-checked copy under `backups/<run-id>.sqlite`. **Inspect copy** re-checks that file in place; applying it over the live database stays unpublished in-app.
3. Stop the owned supervisor (Ctrl+C) or `docker compose down` without `--volumes`.
4. Check out a reviewed commit on `develop` in a new isolated worktree if you are replacing a running preview. Do not treat preview `:8765` as containing later PRs.
5. Rebuild the application image (`./scripts/start.sh`, or `--no-build` only when that image already contains the reviewed commit).
6. Alembic runs on API startup against the existing database. Migrations are additive. Do not copy a backup over the live file unless you are performing a manual, out-of-band recovery you understand.
7. Open `http://127.0.0.1:8765` and confirm health. Existing conversations, Runs, artifacts and settings remain.

This path does not retag unrelated images, migrate other Docker projects, pull GGUFs, or apply a changed checkout automatically.

## Upgrade readiness

`GET /api/maintenance` reports the live Alembic revision versus code head, the application-owned SQLite path, WAL journal mode, active Run count, bind-mount persistence, and interrupted Runs that still need inspection. It is inspect-only. `restore` and `image_rollout` are `unpublished`. A non-loopback bind remains refused. `GET /api/maintenance/backups/{run_id}` re-checks a successful copy without writing. `GET /api/maintenance/image` asks the Host Runner to compare the `ai-station:local` tag with running `ai-station`/`worker`/`scheduler` containers. It never builds, tags, starts, stops or retags.

## SQLite backup

`POST /api/maintenance/backups` enqueues a Task/Run (`station.backup`, executor `sqlite_backup`) with `manage_station` only. Agents do not receive that permission. After releasing the worker transaction, the executor copies the live SQLite file with `VACUUM INTO` into `backups/<run-id>.sqlite`, runs `PRAGMA integrity_check` on the copy, and stores that file plus a JSON report as artifacts. Cancellation is honored before the copy and before artifact registration; a canceled Run deletes a partial copy. Recovery never restores the copy and never retries the Run automatically (`retry_class=inspect`).

`GET /api/maintenance/backups` lists recent backup Runs and their stored artifacts. That list is one keyboard sequence (arrows, Home, End, Enter inspects the backup Run) with unique Inspect names; Inspect copy and Download copy stay on the selected row. System can download the SQLite copy through the ordinary artifact file endpoint. `GET /api/maintenance/backups/{run_id}` opens the stored copy read-only, repeats `PRAGMA integrity_check`, hashes the file, and reads its Alembic revision. A hash mismatch or failed integrity check is reported; the live database is not replaced. Restore remains unpublished because swapping SQLite while the control plane holds WAL connections is unsafe.

## Interrupted work

Conservative recovery still parks uncertain dispatched work as `interrupted` after the owned process is gone. **Mark inspected** records that a person looked at the Run. It does not requeue, restore a backup, or replay side effects. Explicit retry, when a domain already supports it, remains a new Run. System lists currently held leases and expired-lease counts without offering replay; arrow keys move through that list and Enter inspects the Run. If no worker is available, those expired leases stay listed until a worker ticks.

## Compose image inspect

**System → Backup and upgrade readiness → Inspect running image** compares the current `ai-station:local` image ID with running control-plane containers that use that tag. A mismatch means the tag was rebuilt while those containers still run an older ID. Applying that tag, building from the UI, or taking over preview `:8765` stays unpublished. Rebuild from a reviewed checkout in an isolated worktree using `./scripts/start.sh`.

## What remains unpublished

- Applying a backup over the live database
- Building or rolling out `ai-station:local` from the UI
- Taking over a running preview deployment
- LAN publish
