# One bounded correction after an agent's automatic checks fail

Status: implementation candidate, 2026-10-24.

Real research-to-code acceptance (#388) successfully fetched the public sources,
verified their provenance, generated and applied a small static website, and built
its HTML. Its generated Node test imported `test` from `node:assert` and omitted
`assert`; the actual test command correctly failed. Preserve that genuine failure
under `data/acceptance/agent-research-coding-20261024/production-first-generated-test-failure.json`.
No successful build/preview qualification is claimed by that first attempt.

The existing local correction engine already supports bounded validation repairs,
but agent publication always inherited LocalCodingTask's default zero budget.
When a local agent uses a project with explicitly enabled automatic validation,
freeze one correction in its ordinary task request. Use the saved project policy,
including after private workspace creation; agent preferences cannot overwrite an
existing linked project's policy. Projects without automatic checks, standalone
Coding requests, Python/data workflows and external coding retain their contracts.

Reuse enqueue_local_repair, original files/commands/model/worktree, redacted bounded
failure evidence, one immutable agent deadline and Task-wide Stop. Do not retry
network stages or create a new agent/worktree. The first failed validation and
its report stay inspectable. A second failure exhausts the budget; success is
shown only after the corrected checks actually pass. No schema, provider,
permission, arbitrary command or execution-engine change. Disclose the single
attempt with the existing build preferences and a structured Run event.

Test frozen-policy selection and propagation through private workspace and ordinary
proposal publication, a full fake-provider/real-worktree validation-failure →
correction → successful-checks chain, exhausted budget, Stop and original deadline.
Run complete required checks and code review, then qualify actual local behavior
without changing the original failed records or weakening generated checks.
