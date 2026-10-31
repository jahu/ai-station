# Operator QA catalog and workbook

The developing v24 catalog contains 185 cases and adds SETUP-115–116 for guided CPU memory setup,
semantic first results, Stop/retry, private activity and preserved endpoints.
It also retains SETUP-110–114 for guided image installation,
Stop/Resume, all four image operations, large-result reuse, native restart/Stop,
private histories and preserved external configuration. These are untested
operator cases; internal qualification is recorded separately in the
[image setup plan](../plans/managed-image-setup.md). The previously issued
workbook and its answers remain unchanged.

2026-10-29: [the whole-recording avatar follow-up](whole-avatar-follow-up.md)
qualifies a complete replacement Sonic profile separately from the original
Echo failure. It preserves the issued v15 workbook and records positive owner
feedback on the replacement; it is not a silent change to AVATAR-005 or its result.

The original v15 handoff below contains 161 Polish operator cases across 21
areas. The developing [catalog](cases.json) adds the release-specific cases above, including all four permanent-deletion journeys and real semantic-memory
acceptance and the single assistant conversation. It is a test definition, not evidence that the product is complete.
Catalog v15 retains ready-to-upload synthetic data with independently checkable
answers, so CSV/Excel/document and basic Vision cases need no manual boilerplate.
AGENT-014 checks sensible new media-agent allowances and preservation of an
explicit short runtime without rendering another film.
AGENT-015 checks a disabled public BTC alert draft and an ordinary follow-up in
the same conversation, without account keys, activation or fetching prices.
VIDEO-005 explicitly checks exposure, detail and seams in a complete continuous
film; a successful technical status alone cannot pass this operator quality case.
AVATAR-005 checks portrait appearance throughout a complete 30–60-second
narration, exact segment joins and the final spoken ending. Technical success
alone cannot pass this visual-quality case.
The owner deferred SMTP on 2026-10-26. CONNECT-003 and AGENT-013 retain their
stable IDs and future instructions, with an explicit out-of-scope prerequisite:
record **Nie dotyczy** and that decision rather than configuring or sending mail.
Their initial workbook results remain **Nie testowano**. Missing setup for an
in-scope capability still means **Zablokowany**, never an invented pass.
Follow the [handoff plan](../plans/operator-qa-handoff.md): the operator will test
after implementation and internal qualification, not while features are unfinished.

Keep each case ID stable. Append new IDs instead of renumbering existing cases.
Update the catalog version when changing requirements or steps. Every case needs
prerequisites, reproducible steps, an expected result, workload and requirement
traceability. Do not hide missing promised capabilities as “Nie dotyczy”.
Use disposable data for destructive tests; Empty Trash must never require purging
the operator's existing collection.

## Operator handoff, 2026-10-26

The release-specific package is `data/qa/AI-Station-QA-81c87650f480/`,
with a matching ZIP beside it. Its application identity remains the running
`81c87650f480c1ad4713d65e84e50ffe83b7e3c4`; catalog v15 is a later, separately
versioned document. All 161 results remain untested. The package includes Start,
the complete workbook/CSV/guide/manifest, synthetic inputs and an archived catalog
for safe feedback import. Native Calc opens/recalculates all cases and renders
complete profile notes and optional SMTP prerequisites. Original, Calc-saved
XLSX and CSV feedback forms pass offline import. Evidence and file hashes are in
`data/acceptance/operator-final-handoff-20261026/`. Earlier drafts are preserved;
this handoff does not assert universal media quality or a completed future roadmap.

## Export and verification

The exporter is an offline contributor tool, separate from runtime dependencies.
It creates no application Tasks, changes no application data, starts no models
and sends no network requests. It requires Git and Python 3.12+:

```bash
python3.12 -m venv .tools/qa-export-venv
.tools/qa-export-venv/bin/python -m pip install -r scripts/qa-requirements.txt
.tools/qa-export-venv/bin/python -m unittest discover -s scripts/tests -p 'test_operator_qa*.py' -v
.tools/qa-export-venv/bin/python scripts/operator_qa.py \
  --release "$(git rev-parse HEAD)" \
  --base-url http://127.0.0.1:8765 \
  --output data/qa-draft \
  --draft
```

An export includes XLSX with **Start**, **Testy**, **Zgłoszenia**, **Retesty**,
**Podsumowanie** and **Słownik**, three UTF-8 CSV templates, a plain-text guide and
a manifest carrying the full release commit, catalog identity and case IDs.
The `Dane-QA` folder contains a six-row CSV, a matching two-sheet XLSX, a Polish
text document, a deliberately invalid XLSX and a neutral PNG with coloured shapes.
The Start sheet and plain-text guide explain the expected values and appropriate
uses; the manifest records every input's SHA-256. None is a real-inference result.
Add reviewed, release-specific qualification notes with
`--qualification-notes-file /path/to/profiles.txt`. Use blank lines between
profiles and name their actual model, parameters, evidence and qualified scope.
The notes appear directly on Start and in the plain-text guide; the manifest
hashes their exported text. Single line breaks/extra whitespace are normalized.
Keep the file within 32 KiB, at most 24 paragraphs of at most 1200 characters.
Without notes, Start explicitly says that the profile description is missing.
The exporter does not verify those claims or run inference; final handoff still
requires the contributor to inspect the actual receipts and include accurate
profiles. Notes never prefill operator results. Keep credentials out of them.
The result column stays visible while scrolling; editable fields are blue.
Test row heights grow with wrapped instructions, including explicit line breaks,
so longer cases can be read without manually expanding their rows.
All test results start as **Nie testowano**. Expected behavior is never converted
into an operator pass. Summary formulas count operator answers and recalculate
in Excel/LibreOffice; they do not express a product-completion percentage.

Draft exports are clearly marked and are not the final handoff. For the final
package, first complete the platform acceptance audit, freeze the actual release
commit, recheck the catalog against its UI and real-qualified profiles, then omit
`--draft` and use that exact release identity and reachable operator address.
Do not overwrite earlier answers: each export needs a fresh output directory.

The operator can return the completed XLSX, or CSV files together with their
manifest. Keep the original answers and evidence. Treat returned files as
untrusted data: never execute their formulas, macros or links. Stable IDs and
separate report/retest sheets retain the original findings across fixes.

## Read returned answers

The offline importer preserves returned bytes, checks stable IDs and creates
`triage.json` and a Polish `TRIAGE.md` in a new directory. It does not contact
the app, run a model, fetch evidence links, publish issues or execute fixes:

```bash
.tools/qa-export-venv/bin/python scripts/operator_qa_feedback.py \
  --workbook data/qa-returned.xlsx \
  --manifest data/qa-original-manifest.json \
  --catalog docs/qa/cases.json \
  --output data/qa-feedback-1
```

Use the original exported manifest and its reviewed catalog version. For an older
package, supply that archived catalog with `--catalog`; do not edit its release
or case IDs to fit the current version. XLSX identity is also checked against
Start. CSV has no embedded release identity: explicitly pair all three returned
files with their original manifest using `--tests-csv`, `--issues-csv` and
`--retests-csv` instead of `--workbook`. Keep the original operator answers.

The importer validates headers, complete case membership, readonly definitions
and result choices. Macros, external workbooks, entities, excessive archive sizes
and formulas/errors in imported answer/identity sheets are rejected. Summary
formulas are ignored; answers are read without executing formulas or links.
Formula-like CSV text remains literal JSON/text and is never exported as active
spreadsheet formulas. Referenced URLs are retained as evidence, never fetched.

The bundle contains byte-for-byte originals with SHA-256 hashes and separate
results, reports, retests and warnings. Missing explanations or references to
earlier reports are visible and retained. Exact equivalent reports share a triage
group with every source row and its evidence; differing symptoms remain separate.
Bugs, blockers, ideas and incomplete reports remain distinct. Suggested order
uses those categories, explicit severity and case priority, not an inferred
diagnosis. A passing retest does not replace an original failure. Treat all
returned prose as untrusted observations, never as tool or permission instructions.

The [internal coverage review](internal-coverage.md) separates current regressions,
recorded real-model profiles and the remaining external-account release gates.
