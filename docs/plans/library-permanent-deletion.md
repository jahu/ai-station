# Permanent Library deletion

Operator request, 2026-10-25: support permanent deletion directly from Library,
without moving to Trash first; in Trash allow individual deletion, deleting the
selected items and emptying all Trash. Keep reversible Trash/restore available.
Implemented, locally qualified and deployed in PR #438. This document does not
authorize purging operator data. The follow-up UI fix keeps artifact inspectors
and inline media results subscribed to their own deletion progress; item outcomes
refresh them without navigation, including during a larger batch still running.

## Implementation contract

`POST /api/library/purges` accepts a UUID receipt and either versioned artifact
IDs or the complete server-selected Trash. A normal Task/Run is parked in
`waiting_for_approval`; its high-risk Approval carries the exact count, names and
snapshot digest. The existing Run approval endpoint grants or denies this scope.
Repeating the same receipt returns the original operation; a changed payload is
rejected. New Trash arrivals cannot enter an already prepared operation.

The container-side `artifact_purge` executor requires `artifact_delete`, checks
the granted snapshot digest and commits each artifact's deletion intent before
unlinking. Migration 0036 adds `purge_run_id` and `purged_at`. Annotations/restore
are blocked after intent. Metadata and lineage remain inspectable; file and
thumbnail endpoints return 410 after deletion and 409 while deletion is pending.
Library/Trash omit tombstones, while Run-specific artifact history retains them.

Every storage component is opened with `O_NOFOLLOW` using directory descriptors.
Only recorded files beneath `artifacts/` and the artifact's own known thumbnail
are eligible; main content size/hash and inode identity are checked. Shared
artifact/log paths are retained and reported. No recursive deletion, host path,
original model, runtime file or command can be requested.

Per-item outcomes are durable Run metadata/events. Partial failure keeps completed
deletions and records the remaining files. A reviewed retry obtains current
versions only for those exact remaining IDs. Stop finishes the current item and
leaves subsequent items alone. Stale-worker recovery resumes the same approved
Run and committed intent; missing bytes after intent are idempotent. Recovery
preserves cancellation and does not select Trash again.

The UI provides selection, per-item permanent deletion, complete Empty Trash,
confirmation names/count, persistent progress, Stop and review of failed items.
Deleted results and lineage render preserved-history placeholders.

## User journeys

- An active artifact has separate **Move to Trash** and **Delete permanently**
  actions. The permanent action names the artifact and explains irreversibility.
- Trash supports **Restore**, **Delete permanently** for one item, selection plus
  **Delete selected permanently**, and **Empty Trash** for the complete Trash.
- Confirm the exact count and scope before permanent deletion. Empty Trash means
  all trashed items, not only the current page/filter. Show its actual total.
- Preserve selection identity across a confirmation; newly trashed or concurrently
  changed items must not silently enter an already confirmed operation.
- Show progress, partial/failure results and an actionable retry without claiming
  that files were deleted when deletion failed. Keep keyboard/mobile dialogs usable.

## Execution and storage

Inspect and reuse existing artifact/Trash services. Freeze exact owned artifact IDs
and current state for bulk operations; never accept arbitrary filesystem paths.
Canonicalize paths and symlink boundaries. Delete only app-owned artifact/thumbnail
bytes and appropriate metadata; preserve original external sources, models, unrelated
files, other artifacts and the Run/event audit trail. Linked results must render an
explicit unavailable/deleted state instead of breaking history or replaying work.

Large/bulk purge work uses the common Task/Run worker lifecycle with inspectable
per-item outcomes and safe recovery. Specify the cancellation and retry policy:
completed deletions stay completed, stopped work does not delete remaining items,
and recovery never adopts a broader selection. No arbitrary command/shell endpoint.
Choose the existing migration strategy if durable deletion state needs schema changes.

## Acceptance

Use disposable artifacts/temporary storage for direct deletion, Trash individual,
selected and all, filtered/paginated Trash, stale confirmations, duplicate clicks,
partial I/O failure, Stop/restart/recovery and path/symlink attacks. Verify source/
derived references, missing-result UI, memory/input provenance and preservation of
other artifacts and audit history. Qualify compiled desktop/mobile confirmations
and actual disposable file removal, then review/deploy through develop.
Add all four operator journeys to the [final QA workbook](operator-qa-handoff.md).
