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
The complete native UI and preserving restore journey remain to be delivered and
qualified before consumer admission; the command below is a developer interface.

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

## Remaining integration and acceptance

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
and upgrades while recovery is unfinished. This candidate still needs native
dispatch/ownership, retained-file publication and the complete consumer flow.

1. Add native backup selection/progress/cancel and restoration presentation.
   The end user must not need these developer commands.
2. Integrate the image-local restoration candidate with native owned dispatch,
   cancellation and inspection on its attested volume. Its reused pure helpers
   preserve current account/MFA authority, revoke sessions/invitations/node
   credentials, pause schedules, interrupt active Runs and release reservations.
   Unreadable present authority needs explicit reviewed administrator recovery.
   Never run the Linux host Docker/proc guards inside the image or on Darwin.
3. Restore retained files through a durable, resumable journal, retaining current
   originals. Preserve newer credential files required by current MFA authority;
   resolve conflicting secrets explicitly. Do not restore runtime/process/node
   journals or adopt source package/daemon/volume identity. Keep startup fenced
   until files and DB publication agree; support safe abort before publication.
4. Qualify the whole installed Mac journey with real accounts, history, secrets,
   model files, first result, Stop/restart, two-package update, interruption,
   cancellation, backup/restore and data-preserving removal. Native component and
   Linux Docker tests do not prove this consumer journey, Metal or signing.
