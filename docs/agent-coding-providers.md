# Coding providers for persistent agents

Extend the existing isolated agent project workflow to explicit Codex and Cursor
choices alongside Local AI. Reuse worktree preparation, bounded source proposals,
validation, review artifacts, cancellation, deadlines and conservative recovery.
No autonomous commit, push, PR merge or edit of the active checkout is added.

External coding tools must be selected alone, linked to one reviewed project and
use a separate explicit external-coding permission profile. The definition review
must disclose that prompts, guidance and bounded project source reach the chosen
external provider. Local remains the default and cannot silently escalate or fall
back. An external draft stays disabled; the factory defaults it to per-run approval.
Only an explicitly reviewed/activated definition can publish a CLI coding child.

No local response model is loaded for an external coding workflow. The CLI uses its
existing authenticated installation and default model; the local model field stays
exclusive to Local AI. Missing adapters fail with diagnostics, without installing
CLIs or accessing credentials. Operational registry entries need tested permission,
owned cancellation and recovery contracts.

Acceptance uses disposable repositories/fake adapters and checks each provider's
frozen scope, external grant, approval-before-child, isolated worktree, deadline,
validation/review preservation and cancellation. No external private source is
sent during normal verification. Real external smoke testing remains opt-in and
limited to a specifically authorized source scope.
