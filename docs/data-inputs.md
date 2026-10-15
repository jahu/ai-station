# Stored CSV/XLSX inputs and read-only previews

Library → Import file (or drag/drop) accepts UTF-8 CSV and ordinary XLSX up to
16 MiB. Import stores the original as a document Artifact and enqueues an ordinary
`data.inspect` Task/Run. The worker reads the frozen UUID/hash/size, checks the
stored file boundary and returns a JSON preview Artifact linked to its input.
There is no model inference, shell command, network fetch or formula evaluation.

The inspector shows sheet selection, row/column counts, up to 20 rows and 20
columns, literal text clipped to 200 characters and original XLSX row numbers.
Formulas are marked as unevaluated; dates retain stored numeric values. Source
bytes remain unchanged. Refresh preview creates another inspectable Run; Stop,
errors and history use the existing run engine.

Limits: 100,000 rows, 128 columns, 1,000,000 cells, 8 sheets, 128 ZIP members,
64 KiB ZIP central directory, 8 MiB per expanded member, 32 MiB expanded workbook,
500,000 XML nodes per member and 30-second cooperative parsing deadline. CSV
physical lines are bounded to 65,536 characters and the standard CSV field limit.
Macros, encrypted archives, unsupported compression, external sheet references,
traversal names, XML entities/DTDs, excessive or duplicate ZIP entries, invalid
cell references and inconsistent input hashes fail closed. No archives are
extracted and no formulas or macros execute. Uploaded malformed files remain
inspectable originals; failed parsing does not create a preview or modify data.

This enables stored inputs for the isolated Python executor. It does not yet
provide an LLM analysis/transformation agent or imply that selecting a spreadsheet
executes generated code. That workflow separately requires reviewed input IDs,
workspace ownership, Python permission, bounded code/outputs, Stop and recovery.

Normal tests use synthetic CSV and XLSX bytes with a real temporary database and
worker ticks. No private spreadsheet, external provider or model is needed.
