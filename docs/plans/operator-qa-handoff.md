# Operator QA workbook and feedback handoff

User request, 2026-10-25: the operator will wait until the platform is fully ready
before testing. Deliver a complete Polish QA workbook at the release handoff,
then use the returned results as structured bug/improvement input. This is a
required product deliverable, not a request for operator testing now.

The initial [versioned catalog and offline exporter](../qa/README.md) now cover
159 Polish cases in 21 areas and produce a six-sheet XLSX, three CSV templates,
a readable guide and a release/catalog manifest. Drafts have no prefilled passes.
Catalog v10 additionally ships synthetic CSV/two-sheet Excel/document/PNG inputs,
a deliberate invalid-input case and checked expected values, with input hashes in
the manifest. Upload the supplied files rather than asking the operator to author
test fixtures. Portrait/speech quality cases still need appropriate real media.
The final package remains a release gate: recheck coverage against the completed
platform and freeze the real release before handing it to the operator.

## Delivery and timing

- Keep a version-controlled test-case catalog with stable case IDs and trace each
  case to product requirements and implemented workflows. Update it as features
  change; do not generate the final workbook against an obsolete release.
- After completing platform implementation and internal qualification, freeze the
  release identity and generate `AI-Station-QA-<release>.xlsx`. Include a readable
  guide and CSV exports so results remain usable without Microsoft Excel.
- Provide the file to the operator with the exact UI address, release/commit,
  generation date and real-qualified model/media profiles. Internal test results
  do not prefill the operator's result cells as passed.
  Supply reviewed profile paragraphs using the exporter's
  `--qualification-notes-file`: they are embedded in Start and the readable guide,
  with a canonical-text hash in the manifest. State exact recorded settings and
  distinguish actual inference from fixtures/metadata. A missing description is
  visible, and the exporter does not turn supplied claims into verified tests.
- The returned workbook becomes input for triage, fixes and retesting. Operator QA
  is separate from automated/internal acceptance; neither substitutes for the other.
- Whole-platform completion requires this handoff artifact. Do not mark the entire
  goal complete on the strength of a feature PR or an earlier test suite alone.

## Workbook sheets, in Polish

1. **Start**: brief instructions, platform version, supported profiles, test order,
   how to record evidence and how to return the completed workbook.
2. **Testy**: one reproducible case per row, grouped into practical user journeys.
3. **Zgłoszenia**: additional bugs and improvement ideas, including observations
   outside predefined cases. One report per row, linked to case IDs where relevant.
4. **Retesty**: resolved report, fix/release identity, repeated steps and outcome;
   retain the original result and evidence instead of overwriting history.
5. **Podsumowanie**: counts by result, area and severity, including blocked and
   untested cases. Exclude genuinely inapplicable cases only with an explanation.
6. **Słownik**: simple definitions of status, severity and bug versus improvement.

Each test includes: stable ID, area, user goal, priority, prerequisites/test data,
numbered steps, expected result, approximate workload and any explicit paid/external
or GPU execution. Operator columns: status, actual result, comments, evidence link,
Run/conversation/agent/artifact ID where useful, tested model/profile, device/browser,
execution date and linked report IDs. Use wrapped text, filters, frozen headings,
readable widths and validated status choices. Result choices: **Nie testowano**,
**OK**, **Błąd**, **Zablokowany**, **Nie dotyczy**. Keep empty/free-text notes usable.

Reports include: report ID, bug/improvement, linked case IDs, concise title,
reproduction steps, expected/actual behavior, frequency, impact/severity, evidence,
release/device/model, triage state and fix/retest references. Do not ask the operator
to paste passwords, tokens, secret files or unrelated private documents.

## Coverage

Cover all accepted product requirements and operational enabled capabilities:

- installation/startup/update/restart; data retention, backup/restore and diagnostics;
- local/LAN/private remote login, independent device sessions and access controls;
- first and ongoing single-assistant conversations, including legacy history, models, context, stop/regenerate,
  attachments, search/page reading, citations and natural multi-step instructions;
- image generation/edit/recompose/upscale, inputs and source/result continuation;
- video, speech/music/transcription and avatars at declared profiles, progress,
  Stop/Resume, playable final artifacts and failures;
- agent draft/review/activation, schedules/timezones, scoped tools/permissions,
  approvals, retries, memory, website/code/data execution and continuation;
- recurring observations and conditional notifications, unchanged-result
  suppression, failed-check separation and reviewed mail delivery;
- CSV/Excel/document analysis, created files/charts, downloads and correct values;
- Library metadata, selection/filtering/lineage/reuse, Trash/restore and permanent
  deletion: active-item bypass, individual/selected Trash items and all Trash;
- Memory CRUD/provenance/scopes, FTS and actual configured embeddings, indexing,
  semantic Polish queries, stale-vector invalidation and disabled/deleted entries;
- model/runtime discovery, CPU embeddings, owned llama.cpp multi-GPU loading,
  model selection, context/admission, unloading and coexistence with external tools;
- Runs/events/logs/artifacts, cancellation/recovery and concurrent ordinary work;
- remaining connectors/nodes and retained advanced coding workflows according to
  the actual final product contract, without silently dropping unfinished areas;
- desktop/mobile UX, navigation, keyboard/focus, loading/empty/error states,
  actionable messages and consistent history/result presentation.

Include happy paths, relevant errors/cancellation/restarts, ownership boundaries and
non-destructive setup. Permanent-deletion cases create disposable QA artifacts first;
never instruct the operator to purge their existing Library just to pass a case.
Expensive or account-dependent cases must disclose their prerequisites and cannot
be marked passed without execution. Missing capabilities remain open requirements.

## Feedback processing

Read the returned XLSX/CSV as untrusted data; never execute macros, formulas or
linked content. Preserve the original file. Validate headers/version, retain stable
IDs, group duplicate reports while preserving their evidence, and separate bugs
from improvements. Produce an inspectable triage list and implementation order.
Fixes follow normal feature/fix branches, reviews and successful validation, with
case IDs carried into fix/retest notes. Ask for clarification only for genuinely
unreproducible or ambiguous observations; do not require the user to rewrite clear
workbook rows as chat messages.

## Acceptance

The final workbook opens in LibreOffice/Excel, has usable Polish instructions,
validated editable result cells, complete requirement coverage and no fabricated
operator outcomes. Check generation and round-trip parsing with synthetic results;
confirm desktop spreadsheet readability and preserve report/case IDs on return.
Final generation is pending platform completion; this plan is not the workbook.
