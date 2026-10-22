# Scheduled price observations

The deterministic in-app market watch is deployed in PR #340. Reviewed SMTP
foundation is deployed in PR #342, and activation-scoped automatic email in
PR #343. Current source extends the same workflow with scoped Finnhub stock-data
accounts. No trading is performed.

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

## Activation-scoped automatic email

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

A later review found and fixed dispatcher-level Stop for SMTP fanout. It now
uses the existing Task-wide cancellation contract, preserving already accepted
receipts and canceling every active submission/report. Stop current price check
is available in Agents and the conversation. Final focused coverage passed 107
market/agent/TLS cases and 60 UI cases; compiled desktop/phone tests include this
Stop path and duplicate consent reset. PR #343 passed final whole-source gates (1963 Python cases, nine opt-in skips,
546 UI cases), image qualification and compiled desktop/phone acceptance before
deployment. Its proof is recorded under `data/acceptance/market-email-alerts-20261022`.


## Stock-data accounts

Settings → Integrations → Stock prices accepts a named Finnhub account and a
write-only API key. Save performs no network access. Check stock account queues
a separate Run reading the US market-status endpoint; success does not prove
quote entitlements. Account rates and subscriptions remain the provider’s policy.
Keys use SecretProvider storage and only `X-Finnhub-Token`, never a query string.
Rotating an environment/stored key, changing settings or disabling the account
changes the reviewed revision. Health checks and renaming preserve it.

Price watch → Price source → US stocks lets the operator select that account,
explicitly search for a company/symbol, and select up to three symbols. Typing
does not issue requests. Manual symbol entry is also available. Search results
do not establish quote rights/currency. Natural-language stock drafts stay
disabled and do not invent an account or convert a company name into a ticker.
An incomplete draft can be saved; activation requires a current account and
symbols. Missing/rotated credentials block execution while Pause remains usable.

The quote stage requests fixed quote/profile paths and one bounded US status
snapshot. It requires a matching USD NASDAQ/NYSE-family profile; unknown exchanges
are rejected rather than applying US hours to another market. Numeric JSON is
parsed as Decimal. Prices, provider sequence/time, currency, actual market-status
time/session and recent/last-known state are persisted with migration 0031.
Finnhub’s quote timestamp is not represented as an exchange trade identity.
Regular-session data must be at most five minutes old; last-known quotes outside
the regular session may be up to seven days old. The fetch and market-status
evidence must still be recent before publishing an alert. The default maximum
comparison gap is seven days; explicit shorter gaps are respected.

The same comparison, cooldown, notice, Task Stop, approval and SMTP journal are
reused. Stock mail has a separate immutable template/receipt identity and displays
USD, quote as-of time and session freshness. Legacy crypto policy hashes, default
48-hour windows, existing email scopes and crypto template identities stay valid.
No raw credential-bearing provider response/error is saved or sent to a model.
Permission `market_data_read` is additional to `network_read`; uncertain leases
are interrupted without automatic account reads or email retries.

Normal acceptance uses fake data/SMTP in a migrated temporary database. A real
Finnhub key, account quote access and external inbox delivery have not been tested.
See [the implementation plan](plans/stock-price-agents.md).
