# Offline captured-source context

The real #391 conversation qualification found a semantic failure. The initial
public-data analysis returned the exact captured BTC/ETH amounts. Its offline
chart follow-up saw a generic JSON preview truncated before the response bodies,
assumed only URLs were present, omitted the chart, and then repaired the program
using invented `1` values. The resulting Runs succeeded but the source-value
comparison rejected the result. Preserve the failed evidence under
`data/acceptance/conversation-research-data-20261024`; no full acceptance is claimed.
The operator preset was restored and the original checkout was preserved.

## Correction

Reuse the existing verified-source excerpts when a capture becomes an ordinary
offline JSON input. A separate, explicitly excerpted preview shows the actual
`observations[].result.pages[].text` or search snippet structure instead of only
the first 200 characters of a nested cell. It is bounded to 2048 UTF-8 bytes per
input and remains within the existing combined 32000-byte preview limit.
Instructions distinguish response bodies from URLs, require reading complete
input files, and prohibit numeric placeholders for missing/unparsed values.

Verification of original source bytes, hashes, lineage, owner and receipt occurs
before constructing the preview. No public tool, URL authority, refresh, deadline
extension or execution boundary is added. Ordinary CSV/Excel/JSON inputs retain
their previous context. Only captured-source context changes.

## Acceptance

- Regression: real response values remain visible when the generic nested-cell
  preview ends before them; multiple long Unicode sources remain bounded.
- The ordinary conversation pipeline receives these checked excerpts on offline
  follow-ups, with no new research scope or network request. Existing tamper,
  deadline, repair and Stop cases remain required.
- Full local backend/Runner gates, source-identical frontend qualification,
  exact image review and a backed-up controller-only rollout.
- Continue the existing real conversation from its original capture; do not
  repeat the already successful public fetch. Compare exact resulting values
  and review the generated program/chart, then restore the operator preset.

Evidence: `data/acceptance/captured-data-context-20261024`. A model's successful
exit alone is not semantic validation; arbitrary-task quality remains an ongoing
platform requirement.
