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

The compiled UI probe exposed a second restriction: both entry and saved Work
composers forced Web off despite a saved global preference. They now share that
preference with Chat, including an explicit saved opt-out. Upload handling,
continuation and selected-scope overrides retain their existing Web restrictions.
No controls or layout are replaced. UI tests cover first-send Chat/Work defaults,
Work opt-out and retained reviewed image-research queries; compiled acceptance
must use the actual default without toggling it on to hide the regression.

Qualification evidence is retained under
`data/acceptance/work-default-web-routing-20261025`. Both actual local-model
English/Polish requests produced a disabled snapshot-only agent without changing
the ready runtime or its context. Four compiled UI/API/worker flows cover first
Send and saved conversations at desktop/mobile widths, preserving default Web,
reload and source scope; inference is injected in those browser flows. All five
frontend gates pass (794 tests). The complete 3817-case CPU gate initially found
two page fixtures that returned an ordinary answer to the new Work JSON planner.
Corrected fixtures preserve their actual grounded-reply/evidence assertions;
157 complete affected cases and 22 rendered-page importer cases pass. Original
failed logs remain. Final coverage, reviewed-head/image and deployment receipts
determine release status; whole-platform completion is not claimed.
