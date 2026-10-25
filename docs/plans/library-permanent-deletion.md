# Permanent Library deletion

Operator request, 2026-10-25: support permanent deletion directly from Library,
without moving to Trash first; in Trash allow individual deletion, deleting the
selected items and emptying all Trash. Keep reversible Trash/restore available.
Implementation is pending; this document does not authorize purging operator data.

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
