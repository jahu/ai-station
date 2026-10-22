# Scheduled price observations

The deterministic in-app market watch is deployed in PR #340. Reviewed SMTP
foundation is deployed in PR #342. Activation-scoped automatic email is now being
implemented on `feat/market-email-alerts`; it is not deployed or fully qualified.
A stock-data provider remains a separate follow-up; no trading is performed.

The first provider is the public Coinbase Exchange last-trade ticker. Supported
pairs are BTC/USD, BTC/EUR, ETH/USD and ETH/EUR. The operator reviews instruments,
percentage threshold, direction, maximum gap between observations and cooldown
before enabling. No model, API key or GPU is needed for these calculations.

The workflow has separate quote, comparison, notification and report Runs. The
quote stage uses the existing public-address DNS-pinned HTTP reader against fixed
provider URLs. It validates bounded decimal prices, source time and trade identity;
fetch time is not the trade timestamp. Quotes older than five minutes or more
than thirty seconds in the future fail, without updating the baseline.

Comparison uses Decimal arithmetic and the last valid older observation in this
agent's identical reviewed policy. The comparison window is a **maximum gap**,
not a claim of a fixed-period return. Its default is 48 hours so daily checks
retain their baseline despite small scheduling/network delays. First observations establish a baseline;
repeated, corrected or out-of-order trades cannot manufacture alerts. A policy
change establishes a separate baseline. Threshold direction and cooldown are
deterministic. Durable alert identity and atomic in-app delivery prevent duplicate
notices, including replay after a restart. An observation does not imply email
delivery. Every stage remains inspectable and cancelable; uncertain worker leases
are inspection-only, with no automatic repeat of external side effects.

Ordinary tests use synthetic quotes and clocks, migrated temporary databases and
the normal workflow/worker path. Real public reads require explicit opt-in. No
external messages or credential changes are needed to qualify this slice.

Provider contract: [Coinbase product ticker](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker).

## Automatic email candidate

The saved optional email policy selects one existing SMTP connector revision and
1–5 allowlisted recipients. **Enable and allow alert email** requires a separate
unchecked confirmation and records `agent.email.enable` approval for this agent,
market scope, sender, recipients and fixed template. A duplicate has no consent.
Saving a changed policy pauses the agent; re-enabling requires fresh approval.
Changing SMTP settings/credentials or disabling the connector rotates its public
policy revision; health checks preserve it. Pause revokes future authorization.

Only a successful deterministic comparison can publish a same-Task `email_send`
child. Its UUID derives from the MarketAlert identity and template version. The
existing worker rechecks the enabled agent, frozen scope, current approval, source
provenance and freshness before connecting and again before submission. SMTP
transport, Stop, journal and uncertain-result recovery reuse reviewed delivery.
The report depends on published mail children; their independent receipt cards
remain visible even if SMTP fails and prevents the final report. No model writes
automatic messages or selects recipients, and no synthetic per-message approval
is invented. Inspect [the implementation plan](plans/market-email-alerts.md).

Focused qualification: 134 backend cases passed, including the actual private
TLS SMTP sink with synthetic quote → activation consent → threshold → worker
delivery, and 59 focused UI cases passed before receipt-history wiring. Final
compiled desktop/mobile acceptance, full checks and PR review remain required.
No external SMTP account or human recipient has been used.
