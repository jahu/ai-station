# Continue from a transformed CSV or workbook

An analysis can transform a file, but subsequent questions currently reuse its
original input. Preserve that behavior for “this file” and the existing input
button. Add a distinct **Use result file** action and explicit natural references
such as “Sort this result file” / “Posortuj ten plik wynikowy”. These select the
complete verified CSV or preferred XLSX output, never the 20-row preview. The next
operation has a new Task/workspace, while originals and all earlier outputs stay
unchanged. Persistent-agent output uses the same conversation source binding.

After final inert export validation, publish the preferred reusable output ID and
queue its existing read-only data inspection on the same Task. Keep legacy created
file IDs and existing request/definition hashes unchanged. No schema, new executor,
Runner endpoint, or arbitrary filesystem access. Non-tabular reports do not offer
an unusable input. Historical creation output retains its verified compatibility
path; unqualified legacy analysis outputs require explicit inspection/selection.

Current-user result-file intent is separate from ordinary input references. Quotes,
negation, unrelated output/table questions and project-targeted instructions do not
authorize execution. Freeze a result-file flag plus exact source/result/Artifact
snapshots on Send; recheck lineage, completed Python/report bytes, output metadata,
inspection and original hash before dispatch. Missing, changed, trashed, partial,
ambiguous or cross-conversation results must not fall back. Reusing a result grants
no original research, document, memory, agent schedule or email tools.

Show a clear input-versus-result choice with a source link in Chat/Work. Verify a
multi-turn transformation using different original/intermediate/latest contents,
full CSV beyond 20 rows, XLSX preference, created-file compatibility, source changes
at Send/dispatch, failed inspections and project/tool precedence. Run backend/Runner
and frontend gates, exact image/Compose, compiled desktop/mobile continuation and
full-diff review before merge/deployment. Use CPU/fake-model fixtures normally;
record any actual local-model acceptance separately.

Historical ownership, Python/report provenance and full result bytes remain
required. Reusing a result does not reopen original inputs or captures: putting an
original input in Trash does not invalidate a separately retained verified output.
Ordinary input-file reuse still requires the actual original source.

Initial focused qualification: 52 existing publication/creation tests, 20 new
result-reference cases, 39 focused UI cases and TypeScript pass. Tests use injected
model/Python transport with actual private Git workspaces. Full release gates,
compiled acceptance, review and deployment remain pending. Live remains #424.
