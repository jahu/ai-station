# Natural file requests after conversation advice

Browser QA found that “Teraz utwórz prawdziwy plik CSV…” returned instructions
for saving text instead of a real downloadable artifact. The deterministic
creation recognizer omitted ordinary “real/prawdziwy” modifiers. Its Polish
source guard also confused “Excel z arkuszem Produkty” (a workbook containing a
sheet) with a request to read an existing spreadsheet.

Recognize these explicit creation instructions through the existing local
file-creation workflow, including after an ordinary advice turn. Polish source
references retain their grammatical source forms (`z pliku`, `z danych`,
`z arkusza`, `ze źródeł`); containment such as `z arkuszem` does not select an
external input. Existing-input analysis, URLs, quotations, explanatory questions,
explicit Conversation actions and owned coding contexts retain their boundaries.
No new tool, permission, executor, path or model-loading policy is introduced.

Acceptance: in the real unified chat, ask for advice without execution, then
request the three-product CSV from the frozen WORK-001 case with Auto selected.
Verify the actual local Python Run, download all rows, and preserve the initial
failure and separate retest in the private QA workbook. Unit tests alone do not
establish this browser acceptance.
