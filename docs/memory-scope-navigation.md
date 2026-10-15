# Memory scope navigation

Complete the preserved Memory work in an isolated worktree; keep the root WIP
unchanged. Agent/project memory detail links to its owning definition/project
and the existing filtered Runs view. Use clear Open agent/project and View runs
actions in Provenance, with scope-specific accessible names. Global/conversation
memories retain their current actions. These are ordinary links, not execution
actions; never add activation/Run now/coding side effects to inspection.

No schema, backend, permission or execution changes are needed. Retain existing
edit/pin/disable/delete behavior. Port only the focused frontend changes and tests
from the preserved patch, use current documentation rather than copying stale
README changes. Verify focused/full frontend tests, format, lint, typecheck, build,
Docker/Compose and live desktop/mobile navigation. Backend/Runner source must be
identical to the fully qualified PR #318 tree; do not repeat unrelated GPU tests.
