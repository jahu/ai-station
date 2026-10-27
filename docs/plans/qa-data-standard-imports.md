# Fixed standard-library bindings for data scripts

Real WORK-002 browser QA selected the correct local 9B model with observed
129280 context, but both the initial CSV script and its bounded repair placed
`import csv` after `csv.writer`. Both Python executions failed with NameError.
That failure remains recorded; fixing model selection alone did not pass the case.

New data scripts receive `csv`, `json` and `os` alongside the existing approved
`inputs` mapping and `output_dir`. These are fixed imports in the visible,
hashed, persisted source, before model statements and after any module docstring
and future imports. The metadata identifies this scaffold as `data-inputs-v2`.
Existing stored scripts and execution receipts remain unchanged.

The scaffold does not move model statements or infer arbitrary imports. Other
dependencies still require their normal imports. The offline Python sandbox,
read-only inputs, owned output directory, export validation, source byte limit,
bounded repair count and permission checks remain in force. Importing `os` does
not grant shell or filesystem authority outside that sandbox.

Regression tests execute real temporary CSV/JSON exports with missing and late
imports, including future-import headers, and check the resulting files. The
existing workflow tests verify that the audited source and runtime contract reach
generation and repair. Final acceptance still requires rerunning the exact
browser prompt and downloading its actual output after deployment.
