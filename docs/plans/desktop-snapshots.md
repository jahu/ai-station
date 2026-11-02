# Private desktop backups and restoration

The Mac candidate keeps SQLite on an attested local Docker volume because its
tested shared host folder did not provide SQLite writer exclusion. Copying that
host folder alone is not a backup of the station. This work joins the existing
fixed database export with retained application files and native provenance.
Linux/Windows backup behavior is unchanged. Mac consumer admission remains gated.

## Implemented export candidate

`scripts/desktop_backup.py` supplies a trusted, offline installer utility, not a
web API or an agent tool. It accepts a verified installed package and the exact
private desktop configuration. Missing storage ownership never creates a volume.
The native UI candidate is described below; actual installed Mac acceptance is
still required before consumer admission. These commands are developer interfaces.

The caller first stops the station and its owned model/native jobs normally.
Export obtains the existing desktop/update and launcher locks, confirms the
attested database volume has no other clients, inspects bounded state/mount
metadata for containers using the data folder, and checks owned native process
groups with the platform adapter. It neither stops foreign resources nor reads
their environment/credentials. Unknown ownership fails closed.

A backup UUID freezes the verified package, ready version, configuration digest,
volume/daemon identity and namespace. Private request records live at
`<desktop-state>/snapshots/<UUID>/`; backup payloads live at
`<desktop-state>/database-exports/<UUID>/`, outside container-mounted application
data. Two durable markers fence the native parent and ordinary supervisor/API
startup until completion or explicit cancellation. Upgrades/recovery cannot run
concurrently with export.

The existing non-root fixed image command exports the read-only VM database to
an integrity-checked standalone SQLite file. Native code never opens SQLite.
The coordinator verifies source main/WAL fingerprints before and after copying
retained files, then binds both manifests, database receipt and private native
configuration/provenance in `snapshot.json`.

Retained files include artifacts, uploads, thumbnails, logs, runs, worktrees,
telemetry, owned models and credential/key files. Reproducible cache, the database
mountpoint, runtime execution authority and recovery/upgrade transactions are
excluded. Directory descriptors prevent symlink-parent substitution; hard links,
special files, shared-write entries and unexpected mounts are refused. Internal
links remain portable relative links. External resources remain metadata
references; their bytes are neither copied nor granted access.

Lost Docker acknowledgements reconcile the same owned export/read-only helper.
Interrupted file copies resume against their frozen inventory and reuse verified
published bytes; cancellation is checked between chunks of large files. A changed
source or output is preserved for inspection. Explicit cancel keeps originals and
partial output, stops only a verified owned database export when needed and makes
that UUID non-replayable. A new unrelated client cannot prevent cancellation or
be stopped by it. Completed backup verification needs neither Docker nor the
original live source and rejects modified files, manifests and extra DB sidecars.

These backups contain private data for every account and secrets. Keep them in
private storage; they never appear in Library, ordinary HTTP downloads or logs.
Their old desktop/storage receipts are provenance, never live restore authority.

## Developer commands

Use the matching verified bundle's interpreter and script. Paths must be absolute
and canonical. The export command reports its UUID before dispatch; keep that ID
to resume the same operation. Do not run it against a station with active jobs.

```text
<bundle>/python/bin/python3 -IB <bundle>/scripts/desktop_backup.py export \
  --package <bundle> --config <desktop-state>/desktop.env [--operation <UUID>]
<bundle>/python/bin/python3 -IB <bundle>/scripts/desktop_backup.py cancel \
  --package <bundle> --config <desktop-state>/desktop.env --operation <UUID>
<bundle>/python/bin/python3 -IB <bundle>/scripts/desktop_backup.py verify \
  <desktop-state>/database-exports/<UUID>
```

## Implemented restoration candidate

The image-local database restore candidate now supplies fixed `prepare`,
`publish`, `abort` and read-only `status` commands. It packages only the existing
pure `station_recovery.storage`/`.accounts` helpers. Staging and retained raw
original main/WAL copies live on the attested database volume; no native SQLite,
host Docker/proc guards, HTTP or agent restore entry is introduced.

Preparation preserves current account/password/MFA authority and deliberately
revokes sessions, pauses agents, interrupts nonterminal Runs and denies pending
approvals. An unreadable authority requires an explicit named administrator
recovery through a private fixed-path file; passwords never enter argv, reports
or journals. A salted normal account password verifier freezes that request.
Stage migrations and integrity/foreign-key checks finish before atomic DB
publication. Durable source/stage fingerprints and phases allow interrupted
preparation/publication and lost acknowledgements to resume; abort is available
only before publication. A separate volume marker blocks API migration, export
and upgrades while recovery is unfinished.

Native dispatch now reuses the existing storage owner's fixed command journal,
isolation checks and exact helper identities. Restore helpers use a bounded
512 MiB RAM/swap budget, no network/GPU/capabilities, a writable attested volume
and read-only backup/optional private authority input only during preparation.
Completion is cached before helper removal so a lost removal acknowledgement
cannot repeat publication. Owned preparation can be stopped, then inspected and
aborted; an unstarted payload is explicitly distinguishable from an interrupted
transaction. Publication is inspected/resumed rather than blindly canceled.
Disappearing removable input cannot prevent Stop or recovery of an already
dispatched helper.

The full restoration coordinator now joins that database transaction to a durable
retained-file journal. Originals remain under
`<data>/recovery/desktop-<UUID>/originals/`; incoming files are staged on that same
filesystem. Per-root atomic renames and frozen content/directory identities allow
interrupted publication or pre-database rollback to resume without overwriting
unrelated edits. A missing coordinator state after preparation requires inspection.

Current credential files, including newer MFA key files, are preserved. A changed
credential with the same name requires explicit review/keep-current consent;
credential contents never appear in reports. External links remain references,
not permission to copy or modify their targets. Historical configuration, package,
daemon, runtime and volume receipts never replace current installation authority.

The coordinator fences the native parent and application startup until database
and file publication agree. Cancellation before database publication restores
original files and aborts the prepared database. Once database publication may
have started, recovery resumes/inspects that operation instead of attempting a
blind rollback. A verified prepared transaction can resume without its original
removable backup source. Completed requests never rewrite later application data.

```text
<bundle>/python/bin/python3 -IB <bundle>/scripts/desktop_backup.py restore \
  --package <bundle> --config <desktop-state>/desktop.env --backup <backup-folder>
<bundle>/python/bin/python3 -IB <bundle>/scripts/desktop_backup.py resume-restore \
  --package <bundle> --config <desktop-state>/desktop.env --operation <UUID>
<bundle>/python/bin/python3 -IB <bundle>/scripts/desktop_backup.py abort-restore \
  --package <bundle> --config <desktop-state>/desktop.env --operation <UUID>
```

Explicit credential conflict resolution adds `--keep-current-credentials` to a
new restore. Unreadable current account authority instead requires the reviewed
`--recover-administrator <username> --admin-password-stdin` path; the password
travels through stdin into a private request file, never a command argument.
These are trusted offline installer operations; they add no HTTP or agent tool.

## Remaining integration and acceptance

The Mac application now has a **Backups and Restore…** menu candidate. It selects
the current verified installed payload, presents backup/restore consent, and uses
the existing same-user desktop Stop handoff for that exact package. The file/DB
coordinators borrow its desktop lock and independently recheck workload quiescence.
No new lifecycle listener or Docker capability is exposed.

The native folder picker verifies a complete backup before stopping the station.
Progress shows actual stages/file counts; Cancel is cooperative and becomes
unavailable once database publication starts. Closing the window keeps the
operation running. On reopening after interruption, startup offers continuation
or safe pre-publication cancellation. Current credential conflicts require a
separate explicit keep-current decision. Successful exports can be revealed in
Finder; terminal commands are not needed for this ordinary path.

The exceptional administrator recovery candidate is also native. The restore
review offers a separate recovery form for unreadable current account authority.
It requires an administrator from the backup, a new password entered twice and
explicit acknowledgement that MFA is reset and other restored accounts are
disabled. Password fields are secure controls; their bounded JSON reply travels
only through a private child pipe. The native utility reuses the application's
pure username/password rules, packaged without database dependencies, and writes
only the existing private fixed-path authority input. The developer CLI uses that
same validator/writer. A frozen pending request cannot be overwritten with a
different password.

Startup failure offers **Backups and Restore…** even without the web interface.
A stopped `starting` version with a recorded prior ready installation can be
restored using the current verified package, volume and namespace. Native recovery
must acquire its private desktop lock; it never signals an unready/unknown owner.
An unqualified first start is refused. Recovery preserves the `starting` receipt;
only a real API readiness acknowledgement can publish `ready`. Backup creation
still requires a ready installation. Historical backup receipts remain provenance.

1. Qualify the native menu, selection, cancellation/restart and credential review
   on both Mac architectures, then the real installed Docker Desktop journey.
   Include the secure administrator form and recovery from a failed restart;
   component tests do not replace actual installed-device qualification.
2. Qualify the whole installed Mac journey with real accounts, history, secrets,
   model files, first result, Stop/restart, two-package update, interruption,
   cancellation, backup/restore and data-preserving removal. Native component and
   Linux Docker tests do not prove this consumer journey, Metal or signing.
