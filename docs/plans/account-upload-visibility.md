# Member upload visibility after station backups

During the 2026-11-07 dedicated demo-account exercise, valid audio uploads
returned 201 but could not be reopened or used as speech references. The stored
owner was correct. The same account could read its generated outputs.

The backup-protection criterion used `NOT (run_id IN backup_runs)` combined with
a protected-path check. Uploaded artifacts have a NULL run ID. Once the database
contains a backup Run, SQL's three-valued logic turns that predicate into UNKNOWN,
which filters ordinary member uploads. Empty temporary databases masked this
condition in earlier upload tests. Administrator access masked it in daily use.

Use a correlated EXISTS predicate for the backup Run classification. NULL input
Run IDs then correctly mean no matching backup; backup paths and actual backup
Runs retain administrator-only protection. Owner filtering and demotion checks
remain unchanged. No ownership reassignment, data migration, role elevation,
new capability or external-runtime modification is needed.

Regression cases create a real station backup, then upload an image or WAV as
a member. They verify direct access, bytes, Library visibility and worker-scoped
source access, while denying both foreign users and access to the backup.
Both cases failed before the fix. The focused account, backup, Library, media,
purge and privacy suite passed 157 tests; global Ruff lint/format also passed.
Deployment and real demo-account speech qualification are recorded separately.
