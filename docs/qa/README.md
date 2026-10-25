# Operator QA catalog and workbook

The versioned [catalog](cases.json) contains 156 Polish operator cases across 21
areas, including all four permanent-deletion journeys and real semantic-memory
acceptance and the single assistant conversation. It is a test definition, not evidence that the product is complete.
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
The result column stays visible while scrolling; editable fields are blue.
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
