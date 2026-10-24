# Create useful files from instructions

## Observed gap and user outcome

The existing local Python/data workflow can produce CSV, XLSX, PNG and text, but
requires uploaded data or reviewed public research. The native typed Python
executor already accepts zero input files. Creating a new workbook/table/chart
from current instructions should not require uploading a dummy file, registering
a repository or fetching an unrelated public page.

Reuse the same private workspace, selected fitting local model, generated script,
owned offline Python process, verified exports, inline results and Library. This
is a distinct explicit **Create files from instructions** operation, alongside
**Analyze files or public sources**. Support direct Chat/Work and persistent agents.
Do not introduce an unrestricted shell, new sandbox, package installer or runtime.

## Frozen scope and legacy identity

Add a strict `operation` field to the shared data scope: analyze (default), create.
Omit the default from serialization to preserve existing receipt hashes, agent
consent/definition identities and saved scope comparisons. Empty analyze inputs
remain invalid without separately reviewed public research. Create accepts no
uploaded input IDs or research tools: analyzing sources can already export files.
Reject conflicting scopes instead of silently dropping selected inputs.

AgentDataScope, ResearchDataScope and conversation DataScope have different empty
input contracts today. Preserve those distinctions with explicit validated intent;
do not globally remove the min-input protection or infer permission from absence.
Only the frozen create operation can pass zero inputs through freeze/verify,
preparation, generation, repair and result/adoption. Recheck it against the exact
root user message or persistent definition on every attempt. Keep all existing
Task/deadline, Stop, permission, hash and worktree ownership checks.

Native `PythonRun.inputs` and controller `input_artifact_ids` already accept empty
lists. Reuse that path, with the script as its separate verified artifact. Empty
inputs grant no filesystem or network access. The sandbox stays offline with
fixed trusted image, CPU/RAM/process/time/output bounds, no writable original
files, host home or Docker socket. No new host operation or schema column.

## Prompts, outputs and provenance

Generation must know this is creation from the current instructions, not an
analysis of nonexistent inputs. Empty input_map is intentional. No invented
observed data, prices, source reads or downloads. The user's specified constants,
structure or clearly labelled illustrative data can be used; unavailable factual
inputs must remain unavailable. Do not turn a URL mentioned in an instruction
into network permission. Research-based output still uses the analyze operation
and its reviewed source tools.

Reuse exact required JSON/CSV plus existing requested/optional export allowlists
and inert validators. A requested workbook/chart must actually exist before
success. Preserve the script, result and Run/user-instruction provenance even
without source-file parents. No formula/macro/external-link XLSX bypass, arbitrary
output paths or directory scanning. Repairs retain the original intent, output
requirements, permissions and deadline without adding inputs or tools.

## Conversation and agent UX

Offer a concise two-choice operation control in the existing data tools, shared
by Agents and Chat/Work. Show creation from instructions and the actual result,
not a misleading zero-files-analyzed message. Preserve selected file/research
scopes when switching: do not silently drop them. Creation is available directly
on an empty draft; incompatible selected inputs must be explicitly removed first.
No new workspace or mandatory settings. Keep model/repair controls advanced.

Route clear current-user file-creation requests to this existing local capability
without requiring manual tool selection. Resolve current explicit files, reviewed
URLs and verified prior-data references first; do not intercept “create a chart
from those data”, page design, images/music, or quoted instructions. Generic text
answers remain Chat. Ambiguous creation stays explicit through the data tool.
AI-assisted/quick persistent drafts may propose creation only for a current-user
request; remain disabled for review. Keep external coding exclusive. Existing
notification consent must not survive a changed operation incorrectly.

## Qualification and delivery

Verify legacy schema/receipt/consent serialization and unchanged analysis scopes;
explicit create validation, natural routing priority, saved agent activation,
actual worker zero-input map, immutable intent/output scope, bounded repair,
Stop/expiry and conservative recovery. Use temporary DBs/fake inference in normal
checks; meaningful native CPU validation should independently check all requested
CSV/XLSX cells and a PNG from deterministic instruction constants, with source
script and output hashes. No GPU or account is needed for that CPU check.

Run the full required backend/Runner/UI/image/Compose gates, inspect compiled
1440/390 first/follow-up/save/reload/Stop UX, review the full develop PR and deploy
with backup/persistence/model preservation. A real local-model example may follow
when the new path needs qualification; preserve the operator preset and do not
repeat completed rendered-page tests or download new weights. Full-platform work
remains active after this increment.

## Implemented candidate

The controller omits default analyze operation from serialized scopes. All empty
input checks use the frozen operation/research contract. One shared task selector
preserves incompatible selected inputs; direct clear first Send and disabled agent
drafts derive creation from the current instruction. Native Python is unchanged.
The result checks/inspects its own CSV and optional workbook; a follow-up reads that
owned file as ordinary analysis, not a guessed regeneration. Changed bytes, Trash
or a changed result pointer refuse reuse. Public/current facts and existing-data
references are not silently routed to instruction-only creation.

Focused verification currently passes 34 backend cases and 28 related UI cases.
Full-source local gates, image/compiled UI binding, actual native CPU output proof,
PR review and deployment remain required before claiming release. The CPU proof
uses deterministic injected Python rather than a claim of model inference; original
failed verifier diagnostics are retained when correcting its reader assumptions.
