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

## Qualification and release

PR #416, `feat/selected-agent-families`, base #415 (`87dd0f1`). Source `8543af3`
passed all 3477 normal Python/Runner cases (3468 pass, nine explicit opt-in skips),
with all eight shard exits zero, Ruff lint/format. The final source-audit collapse
is UI-only; the full final frontend gate passes 761 tests, formatting, lint,
typecheck and production build. Exact image/backend/assets and normal/dev/LAN
Compose qualify independently.

Compiled 1440/390 browser cases cover both report and code: first selected-document
request, correct family/source audit, explicit review/enable, finished result and
idle/Run now UI. Reports actually capture/read the document and publish Markdown
without Python or project/worktree setup. Code actually provisions private Git,
launches owned local-coding subprocesses through a private test UDS, applies the
proposal, creates diff artifacts and executes successful stdlib unittest validation.
Independent Chromium interactions with the generated calculator check 12+15=27.
Two code jobs, two validation jobs and two reports complete. The model inference
and model inventory are injected; this is actual native code mechanics, not a
new real-model coding-quality or real GPU test. All original repository bytes stay.

Two separate actual existing llama.cpp calls select report and code for Polish
requests and retain exact synthetic document scope in disabled definitions. The
report schedule is 09:00 Europe/Warsaw; code stays manual with Auto coding policy.
The existing 46,080-token runtime/container is preserved. This qualifies real family
drafting, not future report/code inference. No real mail or private files are used.

Evidence: `data/acceptance/selected-agent-families-20261024`. Earlier fixture failures
are retained: report executor-name/session handling, and a conftest absent.sock
exceeding Unix-socket length in the native harness (fixed by its explicit private
short socket). Final UI/body/source-audit screenshots and gates supersede earlier
passing layouts without changing backend/native source. Use the exact review and
post-deployment qualification to establish live state. The full platform remains
an active objective; selected data-file contexts still use data analysis.
