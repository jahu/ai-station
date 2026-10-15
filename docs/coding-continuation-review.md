# Continuing built projects and bounded cumulative review

## Evidence and current delivery

PR #316 is merged/deployed as `94d1036`. Same-Task recorded check repeats, Stop,
retained results and new build ZIPs passed 1519 backend/Runner tests (five opt-in
skips), 477 UI tests, full checks/Docker/Compose, real native/private browser and
production worker acceptance. Evidence: `data/acceptance/coding-rerun-checks-20261015`.
Original root Memory WIP and original project checkouts are preserved.

Read-only inspection of the existing QA React worktree found 1161 untracked files,
1155 under `.ai-station-validation-*` / `.ai-station-dependencies-*`. Its generated
`package-lock.json` is 32265 bytes. These are actual current files; no inference
was run merely to reproduce the failure. `coding_job.execute_proposal` feeds all
untracked paths to `read_selected` for cumulative review, which rejects hidden
paths, more than ten files, files larger than 32000 bytes and total context over
64000 bytes. `commit_job` reuses those same context limits. Thus ordinary follow-up
and reviewed commit can fail after valid dependency/build work.

## Implementation

1. Reserve the existing root scratch directory namespaces as internal execution
   data in Git source discovery/cumulative untracked scans. Exclude them at the
   `git ls-files` invocation, before bounded Git output is materialized. Do not
   delete old scratch/cache files, change the user's Git configuration or globally
   ignore hidden/credential paths. Tracked changes and ordinary source remain
   subject to the existing path checks; never ignore user source by extension.
2. Separate the model-selected context contract (ten files, 32000 bytes/file,
   64000 total) from local cumulative review/hash verification. Introduce a
   bounded review reader for up to 200 ordinary files, 256000 bytes/file and
   2 MiB aggregate. Canonical paths, no symlink/hardlink/binary reads, source hashes
   and root `.gitignore` exception are shared unchanged. This does not send more
   source to an external provider or grant new file-writing scope.
3. Use that review reader for cumulative/repair review and reviewed-commit
   verification. It must cover generated lockfiles and more than ten previously
   changed files; each individual model proposal remains in its selected scope.
4. Precompute the cumulative diff against the owned task HEAD using projected
   proposal contents before applying writes. Bound both base blobs and encoded
   report size. Keep the current 1 MiB native coding report / 1.1 MiB commit
   request limits unless actual qualified data requires another design. Reject
   an oversized review before applying a proposal; never silently truncate it.
   Recheck source and repository identity before application. Retain previous
   file-removal, repair, cumulative-base and reviewed-commit semantics.
5. Document the remaining selected-context limits honestly. Larger model context
   windows / windowed large-file edits remain a separate planned improvement;
   this increment fixes cumulative project continuation rather than inflating
   the whole-file transport or bypassing permissions.

## Verification

Normal tests use fake completions and disposable owned worktrees. Include real
Git untracked scans with generated scratch entries, genuine tracked hidden-file
changes, symlink/credential boundaries, generated lockfiles over 32000 bytes,
11+ cumulative source files, same selected-file write limits, stale contents and
oversized report rejection before any write. Verify reviewed commit includes
only the checked ordinary files and leaves the original checkout unchanged.

Run full required checks, review a feature PR to develop, merge and deploy only
when satisfactory. For opted-in acceptance use the existing owned QA project and
one small local follow-up through Work after the fix, retaining its Task/history.
No external provider or fresh project/site generation is needed. The original
QA source is `64fb729b-62dc-4df9-8ee9-619b5b7db4ee`, Task
`0d0e7756-2498-4482-bf08-2e96fabfa89d`; re-read state before acting.

Do not repeat already-qualified expensive media jobs to fill waiting time:
`docs/long-media.md` records a real 60-second Wan job and 14.2707-second avatar.
The 60-second draft took about 92 minutes; it does not qualify other profiles.
Continue the broader product goal after this blocking workflow issue is fixed.
