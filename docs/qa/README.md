# Operator QA catalog and workbook

The versioned [catalog](cases.json) contains 160 Polish operator cases across 21
areas, including all four permanent-deletion journeys and real semantic-memory
acceptance and the single assistant conversation. It is a test definition, not evidence that the product is complete.
Catalog v13 includes ready-to-upload synthetic data with independently checkable
answers, so CSV/Excel/document and basic Vision cases need no manual boilerplate.
AGENT-014 checks sensible new media-agent allowances and preservation of an
explicit short runtime without rendering another film.
VIDEO-005 explicitly checks exposure, detail and seams in a complete continuous
film; a successful technical status alone cannot pass this operator quality case.
AVATAR-005 checks portrait appearance throughout a complete 30–60-second
narration, exact segment joins and the final spoken ending. Technical success
alone cannot pass this visual-quality case.
Follow the [handoff plan](../plans/operator-qa-handoff.md): the operator will test
after implementation and internal qualification, not while features are unfinished.

Keep each case ID stable. Append new IDs instead of renumbering existing cases.
Update the catalog version when changing requirements or steps. Every case needs
prerequisites, reproducible steps, an expected result, workload and requirement
traceability. Do not hide missing promised capabilities as “Nie dotyczy”.
Use disposable data for destructive tests; Empty Trash must never require purging
the operator's existing collection.

## Export and verification

The exporter is an offline contributor tool, separate from runtime dependencies.
It creates no application Tasks, changes no application data, starts no models
and sends no network requests. It requires Git and Python 3.12+:

```bash
python3.12 -m venv .tools/qa-export-venv
.tools/qa-export-venv/bin/python -m pip install -r scripts/qa-requirements.txt
.tools/qa-export-venv/bin/python -m unittest discover -s scripts/tests -p test_operator_qa.py -v
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

The [internal coverage review](internal-coverage.md) separates current regressions,
recorded real-model profiles and the remaining external-account release gates.
