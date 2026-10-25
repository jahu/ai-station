# Conditional research-report alerts

An ordinary research agent can currently report on a schedule, but its success
notices/email have no criterion for “only tell me when a significant new finding
appears”. Preserve every report and add an optional, operator-reviewed success
criterion. Failure/approval notifications keep their current behavior. Existing
market threshold logic remains deterministic and unchanged.

Store the criterion in the existing notification-policy JSON, omitting its empty
default to preserve old snapshot/approval identities. This policy applies to
ordinary report agents; code/data/media/market definitions must reject it until
their result-specific comparison is implemented. The UI must retain any existing
criterion when changing tools, require explicit removal for unsupported outputs,
and never silently widen an email policy. Agent Factory may propose a criterion
only in a disabled reviewable draft, with an in-app success channel selected;
email recipients/credentials/automatic-send consent remain operator-owned.

After normal report generation, save its actual Markdown artifact. Within the
same Run, provider and original deadline, perform a bounded, tools-free structured
local-model check of the criterion against that report and the latest verified
successful report with identical frozen definition. Reports are untrusted quoted
data, not instructions. Compare actual findings, not timestamps, formatting or
wording; no previous compatible report is disclosed as no baseline. Freeze source
IDs/hashes and explicit excerpt bounds. Reverify sources before accepting a strict
boolean/reason decision. Do not hold SQLite across inference. Stop must close the
stream, retain the report for inspection and prevent notices/mail/memory writes.

Record criterion, baseline provenance, decision/reason and suppression as events
and Run metadata. A false decision still succeeds, preserves its full report and
ordinary memory policy, and suppresses both success notices and configured result
email. A malformed/unverifiable check cannot send or claim a successful alert;
retain the report and expose failure through normal Run/failure-notice behavior.
True decisions use existing notice/email publication and fresh consent checks.
Expose the criterion in Notifications and the actual decision/baseline in the
results-first agent workspace. Internal classification JSON must not become a
report, chat message or partial-report artifact.

Qualify compatibility, first result, changed/unchanged reports, different agents/
settings, tampered/trash/ambiguous sources, strict outputs, cancellation/deadline,
suppression and reviewed email, factory review and UI save/reload. Complete normal
Python/Runner and all frontend gates, compiled desktop/mobile flows and bounded
actual local-model acceptance without changing the ready model. Review a PR to
develop, then perform a controller-only rollout preserving data/auth/native/model/
private access. This delivers the research-alert requirement; broader result
families, agent composition and whole-platform completion remain open.
