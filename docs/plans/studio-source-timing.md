# Source-aware Studio timing

Actual qualification, 2026-11-12: a six-scene proposal selected a six-second
Library clip and a four-second new video. Its beat weights totaled 38 seconds
for a requested 75-second edit. The unconstrained largest-remainder fitter
stretched the valid Library beat to 11.9 seconds. Both model correction attempts
then failed the source guard. This failure was introduced by fitting; it was not
an attempted use of an originally requested twenty-second source window.

The director now fits beat weights with finite per-scene ceilings. Completed
Library footage is bounded by its observed remaining source window, including
each reused scene's own trim. Elastic still/graphics beats absorb remaining time.
When elastic stills exist, the fitter also avoids automatically lengthening planned
generated-video beats. It never loops, freezes or time-stretches an existing clip.
A bounded water-filling allocation with stable largest remainders preserves the
exact total frame budget, scene order and one-to-ninety-second scene bounds.
Impossible source-only budgets fail with an actionable error. Unknown timing is
not fabricated. The existing unconstrained fit is retained when no bounds apply.

Validation, speech-only editing hints and final director publication use the same
fit. Word bounds and actual speech reconciliation still apply. Retiming is
recorded even when total frames already match but a scene must change. Manual
saved revisions and existing generated artifacts are not refitted or rewritten.
No request schema, stored source snapshot, permissions, native operation or
migration changes. Catalog duration is a planning observation; native inspection
of owned source bytes, hashes and actual final trim windows remains authoritative.

Qualification must cover the exact 38-to-75-second failure, generated-footage
budgets, reused trims, impossible/tiny/unknown windows, deterministic rounding and
invariant frame budgets. A real worker/API test must validate, revise the script
and publish with identical source ceilings. Then retry the original actual
planning request on the corrected build, preserving its failed evidence and
without rerunning the completed film or supplying a fabricated model answer.
