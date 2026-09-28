# Library management

Library manages general Artifacts, not an image-only store. Import uses the existing bounded image/WAV upload adapters; generated outputs retain their Run and parent relationships. Search, type filters and pagination operate on persisted artifact records.

User-editable display titles and notes are separate from immutable generation parameters, original filenames, hashes and paths. Versioned updates reject stale edits. Moving an artifact to Trash hides it from the normal Library and new input pickers; it does not delete bytes or break historical Runs, existing inputs or source lineage. Trash supports inspection and restoration. Permanent file deletion is intentionally separate from this reversible action.

Run-scoped artifact listing includes trashed artifacts for audit continuity. Direct inspection and media delivery remain available locally. Mutations on Run-owned artifacts append structured events; metadata operations do not create execution Runs. Migration 0005 adds the library fields without moving media files.
