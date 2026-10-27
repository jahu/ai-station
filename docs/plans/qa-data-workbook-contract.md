# Actual XLSX analysis and workbook export

The first post-fix browser retest of DATA-002 successfully read the approved
input mapping and reached the calculations, but then failed in an optional
workbook export. The first generated program referenced an unimported
`openpyxl`; its one permitted repair imported `Workbook` but retained
`with Workbook()`, an API openpyxl does not provide. Both failed source artifacts
and stderr remain in the private QA evidence. Input bindings alone do not close
this issue.

Make the existing generation contract concrete: import the library, construct a
workbook normally, append values, and save to the approved output directory.
Read-only inputs close explicitly. Generated code still runs only in the
existing offline owned Python workspace. Do not monkey-patch third-party
objects, execute model code in the control plane, silently rewrite its logic,
increase the reviewed repair budget, or publish failed partial outputs.
Optional exports follow the current request: an Excel input is not a request to
also create a workbook, chart and text report. Ordinary calculations already
have their mandatory result table and complete CSV.

Acceptance requires a fresh actual browser analysis of both sheets in the frozen
QA workbook, correct six transactions/150 total/A65/B85, an original-file hash
check and a working full-result download. Additional guidance is not itself
proof of successful generation; rerun and record the result honestly.

## Fixed market adapters

The parallel real AGENT-015 draft now validates and keeps the correct reviewed
numeric scope, but model prose promised a rolling 48-hour average. The actual
adapter compares the previous valid observation within the maximum gap; it does
not fetch historical averages. For controller-recognized market drafts retain
the original user goal and controller definition text instead of publishing a
model's invented calculations. The model may still supply a useful display name
and cadence. This applies to new disabled drafts only and never rewrites an
existing agent. Acceptance still requires a fresh disabled BTC draft, matching
visible policy, no executions, and a normal arithmetic follow-up in the same chat.
