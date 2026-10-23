# Generated analysis files

Extend the existing local Python/data workflow in Chat and persistent Agents to
return actual generated charts, Excel workbooks and text reports. Preserve the
mandatory verified answer/table/CSV and the existing explicit file selection and
natural same-input follow-ups. This is not a second execution engine.

The local model may declare up to three unique, fixed optional filenames:
`chart.png`, `result.xlsx`, `report.txt`. Freeze that declaration before dispatch;
Python must produce exactly the declared outputs, plus the existing two required
files. Existing source, worktree, input hashes, offline container, resource limits,
deadline, repair, cancellation and recovery contracts remain authoritative.
No arbitrary paths, extra input access, packages or network are model-selectable.

The optional CPU Python image includes a pinned Matplotlib with the noninteractive
Agg backend and temporary configuration/cache. An explicit installed-image feature
label is observed through the existing Runner capability endpoint. Legacy images
retain table/CSV operation; unsupported chart declarations fail with setup guidance.
No model download is involved. The host never imports generated Python.

Only format-checked files are published as usable exports. PNGs have bounded
decoded dimensions and are re-encoded without supplied metadata. XLSX packages
use the existing bounded archive/XML reader, reject formulas/macros/external links
and embedded/active content, and enforce existing sheet/row/cell limits. Text is
bounded UTF-8. Raw optional Python outputs stay internal and cannot be downloaded
as validated exports. Validate the complete set before publishing any exports.
Each usable file retains the exact raw output, script and original-input lineage.

Show the verified chart inline, with clear PNG/Excel/report downloads and Library
inspection, on desktop and mobile. Persist identifiers in the existing result
metadata; no migration or changes to public submission/receipt fields are needed.
Legacy results have no export list and keep their current presentation.

Qualification: invalid/duplicate filenames; frozen declaration tampering; missing,
extra, changed, oversized and invalid files; PNG metadata/animation/pixel limits;
XLSX zip bombs, formulas, external relationships and embedded payloads; legacy
runtime/results; existing repair/Stop/recovery and same-file follow-ups. Use fake
inference with real disposable workspaces for normal tests, compiled desktop/phone
checks, full required gates and reviewed images/PR to develop. Separately qualify
one actual local-model CSV-to-chart/Excel request through the normal worker and
native offline Python; verify source hashes and restore the operator model preset.
Do not claim the feature deployed or that real inference ran until evidence exists.
