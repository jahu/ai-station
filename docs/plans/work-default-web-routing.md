# Work actions with default Web availability

Read-only implementation inspection found that default-on Web consumed otherwise
unclassified Work instructions before the planner, and rejected even deterministic
agent/workstation actions as incompatible research. A normal request such as
“Could you prepare an agent…” therefore queued a text reply instead of a disabled
Agent Definition. Three ordinary-worker regression cases reproduce this failure.

Web availability is a preference, not an instruction to research every action.
In Work, an enabled Web option with no custom query or JavaScript-page request
must preserve deterministic actions and let unclassified current instructions
reach the existing selected-model planner. Chat mode and explicitly selected Chat
remain ordinary conversation/research. Custom search queries and rendered-page
requests retain their existing explicit scope and incompatible-action checks.

Reuse the current Task/Run/planner/action services. Normalize the passive option
before enqueue for already resolved Work actions; retain an inspectable skipped
Web event when an ambiguous Work instruction is later resolved to a non-research
action. Never grant an agent search tools merely because Web was available in the
composer. Agent definitions remain disabled for review. Runtime/Git/project
scopes, Chat/Work policy, provider disclosure, deadlines, Stop and receipt replay
retain their server-side checks. No executor, schema or arbitrary tool is added.

Qualify ordinary and polite English/Polish agent requests, current workstation
inspection without a model, searched conversation replies, explicit query/render
scope, selected Chat, missing runtime/commit authority, cancellation and receipt
replay. Use fake inference in normal tests and compiled desktop/mobile UI; run a
bounded real local inference acceptance in isolated application data only when
the existing runtime can be reused without changing its presets. Complete local
gates, full review, PR to develop and a data/model/private-service-preserving
controller rollout. Do not count this fix as full-platform completion.

Planner reference context uses saved plain `user_text` rather than expanded
attachment bodies, and skips older attachment messages without that plain text.
The current plain instruction also determines its history budget. This is needed
because a newly reachable Work planner must not acquire incidental file text on
ordinary researched follow-ups. Existing bounded verified result references stay.
The legacy orchestrator alias is normalized to Work for passive-Web preflight,
so ambiguous images still obtain the selected planner/provider snapshot.
