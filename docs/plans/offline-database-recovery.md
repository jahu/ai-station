# Safe offline database recovery

Current maintenance can create, inspect and download consistent SQLite backups,
but cannot safely apply one. Add an operator-only host command; the HTTP API and
workers must never replace the database beneath open WAL connections. Existing
Docker/native execution boundaries and backup Runs remain unchanged.

## Operator flow

1. Inspect a successful backup in Settings → Maintenance. The existing SQLite
   copy does not include artifacts, worktrees or model files; keep the original
   application data directory.
2. Run `./scripts/restore.sh --backup-run <uuid>` to inspect the copy without
   changing the live database. Report its digest, schema, record counts, missing
   application artifacts and the recovery actions. Never print credentials.
3. Unload AI Station-owned models, finish/stop workloads and stop its supervisor.
   Apply only with the reviewed backup digest and an explicit `--apply` flag.
4. Preserve a private rollback copy, stage and check the restored database,
   atomically replace it, write a durable receipt and start normally. Agents
   remain paused; uncertain work remains interrupted for inspection. Nothing
   automatically replays or starts during recovery.

## Required guards

- Accept only a canonical UUID backup under this configured data root. Reject
  symlink escapes, unexpected hard links, changed bytes and unknown/future schema.
  Known ancestor revisions migrate through Alembic on the private staging copy,
  using an explicit connection rather than the configured live database engine.
  Require an integrity/foreign-key checked copy and its retained artifact files.
- Hold the same launcher lock through the whole apply. Refuse live containers
  mounting this data directory (including owned model/preview containers), owned
  native process groups, open database users or unconfirmed inspection. Inspect
  only; never stop unrelated services or expose Docker through an API.
  Descriptor inspection excludes protected desktop Chromium/PAM/service-manager processes, which
  are not database executors; AI Station-owned Chromium jobs remain covered by
  container mounts and native process ownership. Unknown inaccessible executors
  must still block recovery. Do not claim visibility into arbitrary protected
  host applications or require stopping the operator's desktop for recovery.
- Preserve current operator credentials and login budget when readable. Revoke
  restored device sessions and node invitation tokens. If the current database
  is unreadable, require a fresh operator password through a private file or
  terminal input rather than reviving an old credential silently.
- Pause restored agents, park nonterminal Runs, deny stale pending approvals, clear stale workers/leases and
  release obsolete resource holds. Mark historical managed runtimes stopped only
  after the host guard has proved that no owned model container remains alive.
  Preserve completed history, memory, settings, artifacts and owned worktrees.
- Stage normalization against a private copy. Back up the original database and
  any WAL sidecars before replacement. Failure before replacement leaves the
  original usable. Record hashes/actions and rollback location without secrets;
  no destructive cleanup or model download.

## Qualification

Use disposable migrated databases, owned temporary files and fake host probes in
normal tests. Cover busy startup/containers/native groups/open DB handles, schema
and digest changes, path boundaries, missing files, corrupt current DB, auth/session
preservation/revocation, paused schedules, interrupted work, output receipt and
failure before replacement. Run the actual host CLI against a disposable data
root, then start an isolated API on the restored copy and inspect retained data
and authentication. Never restore over the operator's production database for a
smoke test. Full local checks and reviewed PR-to-develop gates remain required.

This plan does not claim recovery is implemented. The whole-platform objective
remains active, including general-agent composition, media/resource quality,
recognition-quality approval and actual private remote access.
