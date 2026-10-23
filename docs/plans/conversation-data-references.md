# Natural follow-up questions about analysed files

Current gap: completed CSV/XLSX results offer an explicit “Ask another question”
selector, while a natural request such as “Policz średnią z tych danych” has no
file scope and falls back to ordinary text chat. Reuse the existing conversation
Python/data pipeline; add no executor, schema migration or model download.

## Authority and resolution

Only an Auto action in Chat/Work with a current, explicit file/data reference and
an analysis/calculation instruction may reuse inputs. Explicit data, attachments,
images/audio, other tools/projects/Work continuations, exact Web queries and
rendering retain precedence. Bound Work contexts also suppress implicit selection.
Ordinary Web availability is disabled for a recognised offline data request.
Unrelated chat and interpretation of quoted instructions must not start Python.

Resolve the latest file-bearing user turn in this conversation, using a bounded
history scan. A newer different attachment is a barrier and retains ordinary Chat handling;
absence of any prior data source also retains ordinary Chat. A failed, cancelled,
unverified, superseded or unavailable latest analysis must never fall back to an
older one. A singular file reference with multiple inputs requires explicit
selection; collective data/group references may reuse the reviewed set. Inputs
are original CSV/XLSX sources, not a generated result CSV. Explicit result/table
references retain ordinary chat/explicit selection rather than guessing a file.

Validate the prior user→orchestrator→private setup→data workflow→verified Python
result ownership and exact frozen inputs. The former execution may be expired;
read-only provenance validation must not reactivate or extend its budget. Current
source metadata/inspection must still match the original snapshots. HTTP handlers
perform bounded metadata resolution; workers retain actual byte/hash verification
before workspace/model/Python work. Missing/legacy/changed provenance fails closed.

Freeze source IDs, prior question/answer snippets and input snapshots into a
controller-owned reference on the new user message and Run. Enqueue checks that
new input snapshots equal the selected old scope; the worker revalidates before
creating a workspace. Existing origin checks retain that reference. Prior question
and result are bounded, untrusted context for interpreting the follow-up, never
permissions or tool instructions. Do not recursively carry the entire history.

## Execution and UX

Create a normal new Task and private data workspace with the prior reviewed local
model/repair/runtime policy, a fresh bounded deadline and the same inspected files.
No persistent Agent or manual repository is needed. Keep originals read-only.
Existing cancellation, retries, conservative recovery, actual-model disclosure,
answer/table/CSV/script artifacts and the explicit file selector remain in use.
The conversation clearly labels “Using the analysed input files” and links the
source Run. Reload restores the source annotation. The current question wins
when it changes an earlier filter or calculation.

## Qualification

Fake provider plus disposable real Git/Python fixtures: Chat/Work natural follow-
up, same ordered IDs/frozen snapshots, old completed/expired origin, quoted bounded
context, independent Task/workspace, two successive questions, repair history,
foreign/missing/forged origin, inspection/hash/Trash changes, missing/failed/latest
analysis and newer-attachment barriers; singular/group ambiguity; explicit scope,
Web/project/mode precedence; idempotent receipt, worker-time tampering and Stop.
Compiled desktop/390px ordinary upload→first result→natural follow-up→label/table/
source link/reload/Stop. Full Python/Runner and UI gates, Docker/Compose, full PR
review to develop and backed-up rollout. Then one real short synthetic same-file
follow-up through normal local-model/native Python, checking numeric results and
restoring the operator model preset. Do not claim inference or download not run.
