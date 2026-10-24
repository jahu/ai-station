# Match selected-document agent drafts to the requested job

A document/reviewed public source can describe a report or software task, not only
Python analysis. Extend the existing selected-input Agent Factory with a bounded
family choice: data analysis, local report, or local code. Keep Task → Run → Events
→ Artifacts and the existing source/Stop/replay/publication checks.

CSV/XLSX/JSON data selections and instruction-only file creation retain the data
family. Document/public-source-only selections allow all three. The model chooses
one allowed family and drafts identity/goal/schedule. It never chooses tool names,
source IDs/URLs, project, model, permissions or execution limits. The controller
maps the family to existing operational tools; source readers stay exactly fixed.
Unsupported family choices fail validation and may use the existing one correction.

Data keeps its selected local data model and existing Python pipeline. Code uses
coding_local with the same reviewed context and selected/Auto coding model, a fresh
owned workspace and ordinary checked project preparation (public dependencies and
build checks visible in the existing review). Report uses only selected readers
and the explicit selected model, or the originating local Chat model for Auto.
Only explicit enable/run grants future tool permissions; drafting still reads no
public source, runs no code and creates no project/worktree.

Do not change request/definition schemas, existing saved agents or source snapshots.
An absent proposal family means data for compatibility. Source cards must stop
claiming every selected-input agent creates a workspace; show the actual prepared
family and distinguish selected readers from future execution tools. Preserve
existing data/analysis-result behavior and expose the real family in the review.

Verify family containment, unchanged inputs/source/model/runtime boundaries,
report without Python/workspace, local code with document context and owned Git
review, explicit enable, Stop/tamper/replay, legacy absent-family proposals, compiled
desktop/mobile and actual local inference separately. Qualify final source locally
before PR to develop and data-preserving deployment. Current live baseline is #415.
