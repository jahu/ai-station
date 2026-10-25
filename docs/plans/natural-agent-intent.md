# Natural agent requests in the single conversation

Release-audit finding after PR #444: “Could you prepare an agent…” and
“Chciałbym mieć agenta…” were treated as ordinary questions. With default Web
enabled, the direct reply path could search the requested goal instead of
preparing an agent. Two actual API/worker regressions reproduced the wrong route;
the other 99 Web/page checks passed. This is a routing defect, not a reason to
restore a user-facing Work mode.

Use one current-instruction predicate for plain agent creation, selected inputs
and references to a completed analysis. Recognize polite requests, desire forms
and bounded descriptive agent names in Polish/English. Route recognized creation
deterministically into the existing disabled-draft factory; it needs only the
factory inference, not a separate model classification. Default Web availability
is omitted for this action. Explicit search queries retain their existing mixed
scope checks and must never be silently discarded.

Information requests, quoted instructions and negation do not authorize creation.
“Explain how to create an agent”, “Create a description of an agent” and
“Write a prompt for an agent” remain ordinary replies. Selecting the explicit
Agent action remains a deliberate override. Do not infer permission from tool
results, attachments, stored messages or an LLM planner suggestion.

Selected CSV/Excel/documents and completed-analysis references retain their
existing frozen ownership, source hashes, tools, context and future workspace
contracts. Drafting starts no code execution, network tool, schedule or enabled
agent. Legacy explicit API policies remain compatible. No native operation,
database schema, global permission or new execution mechanism is introduced.

Acceptance: default-on Web with polite creation; ordinary informational and
negative controls; selected-input and completed-analysis drafts in the same
conversation; source preservation and disabled activation; Web search and direct
page reads under assistant policy. Run current full backend/Runner gates,
unchanged-frontend proof, exact image/Compose and compiled desktop/phone
API/worker checks before review, merge and data-preserving rollout. Evidence:
`data/acceptance/unified-natural-agent-intent-20261025/`.

## Qualification

PR #445's frozen source passed the complete normal suite: 4,114 Python/Runner
tests, nine opt-in integrations skipped, and Ruff/format. The entire frontend
tree is identical to qualified PR #444, retaining its five successful UI gates
and 844 tests. Exact backend/compiled image assets, all three Compose variants,
isolated image API/worker/SQL/SSE and six QA exporter checks passed. Catalog v8
retains the same 156 case IDs and adds polite/default-Web steps to UNIFIED-002.

Compiled 1440/390 checks used the actual isolated API/worker with fake local
inference and CPU image fixtures. English/Polish polite requests with Web on
prepared disabled agents while a forbidden-search spy recorded no query. Two
ordinary responses and two agent drafts needed four model calls total. Existing
translation review, inline recovery/reload, draft preservation and Stop passed.
Source mappings, review, merge and deployment receipts in the evidence directory
determine the live release. This does not claim a new real model/GPU smoke or
complete the full-platform acceptance/QA handoff.
