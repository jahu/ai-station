# Conversation continuation after web search

## Observed failure and cause

The 2026-11-11 SQLite binding repair removed a lost decision lease. Repeating
that conversation reached a successful search but ended with the generic
"I could not choose a valid next action" clarification. A completed controller
was not proof of a useful answer; acceptance must inspect its outcome and reply.

A private read-only reproduction on the same loaded local model proposed reading
URLs from the actual search results twice. The tool expected internal source
aliases, and its 100-character alias field rejected longer source URLs as well.
The correction did not change that representation. This was an input-binding
mismatch, not missing user intent or a failed search.

## Repair

Before typed alias validation and duplicate-call comparison, bind an exact URL
already present in the originating controller's source catalog to its existing
alias. Keep canonical aliases in the accepted decision and dispatch receipt.
Never infer new destinations, match prefixes/domains, decode/normalize URLs or
fetch arbitrary model proposals. Unknown sources remain rejected; the existing
public-address, redirect, DNS and response-size checks still govern actual GET.
The catalog belongs to the live owner-scoped originating controller, not a
model-supplied replacement. Network selection and tool permissions are unchanged.

The tool schema explicitly describes source keys. Bounded rejection events record
attempt/retry counts without exposing raw framework output or private reasoning.

## Acceptance

Fake-model integration covers search → observed long URL → page read → streaming
answer, untrusted page roles, unknown/changed/private URLs and alias-versus-URL
repeat suppression. Run the surrounding controller, ReAct, page-fetch, provider,
SQLite binding and privacy regressions before merge. Deploy only the worker
modules after idle checks and a consistent database backup, preserving the loaded
model and API. Real acceptance requires an actual final answer using the retrieved
sources; a generic fallback or merely terminal Run status does not qualify.
