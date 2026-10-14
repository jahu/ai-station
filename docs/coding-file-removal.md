# Selected source removal

Local AI, Cursor and Codex may remove an existing selected UTF-8 source file
using `{"path": "obsolete.py", "delete": true}`. Providers still have no native
write tools. The Runner applies the checked proposal inside the allocated
worktree while holding its mutation lock, through the ordinary Coding Run.

Paths must be selected and canonical. Directories, symlink/hard-link redirection,
hidden/credential paths, nonexistent files, coerced flags and mixed delete/write
objects are refused. Every selected source is checked against its captured
content, hash and mode before any change. Interrupted application preserves
partial work for inspection and never publishes success from an unknown outcome.

The review labels removals **Deleted**, records the original hash and a null
output hash, and includes a reversible Git patch with executable mode and line
counts. Follow-ups retain earlier removals in the cumulative diff against the
task HEAD. Repair Runs may retain those intended removals but cannot introduce
additional removals to bypass failing validation.

Commit remains a separate reviewed Run with validation and protected-branch
checks. The path must remain absent, the parent must be unchanged, and its tree
must contain the matching ordinary source blob. Recreated or redirected paths
fail before ref advancement. The private index removes only reviewed tracked
paths; unrelated worktree changes and the source checkout remain untouched.
No push, PR, merge or deployment follows automatically.

Tests use fake providers and disposable real Git repositories. They cover
empty/nonempty/executable patches and reversal, stale/symlink rejection,
reviewed commits, cumulative follow-ups and repair refusal before any writes.
Those tests do not claim a real-provider removal.
