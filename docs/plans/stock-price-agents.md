# Stock observations for price agents

The optional account adapter was deployed in #344 after local qualification.
Real-account acceptance is unverified and is not required for ordinary research.

## User correction and default path — 2026-10-22

The stock-price examples illustrated general agent capabilities, not a request
to require financial-service accounts. Use free public sources in tests and
ordinary research; do not request API keys to prove those examples. Stop expanding
specialized quote providers as a completion prerequisite.

A stock-research instruction without an explicit Finnhub request creates a
disabled general-agent draft, preserving the selected local model and existing
public search/page tools. A quoted public query or supplied URL is retained for
review; otherwise the user reviews the public query before activation. Never send
the entire private goal, email address or memory to search to save a form field.
Existing keyless Coinbase BTC/ETH watches and explicitly selected Finnhub scopes
remain compatible. No credentials, schema migration or new executor are added.

Public research returns source-linked findings, not guaranteed current quotes,
deterministic threshold monitoring or implicit email delivery. The existing typed
price/email workflow remains available when the operator explicitly chooses it.
Do not rewrite saved agents or migrate their previously approved scopes silently.

## Provider contract checked on 2026-10-22

Finnhub documents US stock quotes, company profiles and current market status.
Authentication supports the `X-Finnhub-Token` header; account limits can return
HTTP 429. The quote's `t` is documented as a timestamp, whereas market-status `t`
is current time. Preserve these distinct meanings; do not invent a trade ID or
trade timestamp. Quote access outside US markets depends on the provider plan.
Sources: [authentication](https://www.finnhub.io/docs/api/country),
[quote](https://finnhub.io/docs/api/quote),
[official OpenAPI](https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml).

The first profile targets USD stock quotes through a user-configured account.
Do not claim all exchanges, indices or currencies, scrape a browser's credentials,
use exposed third-party keys, assume an account's entitlements or add trading.

## Delivery plan

1. Add a typed Finnhub market-data connector using existing Connector and
   SecretProvider storage. It has no configurable URL/port and never returns the
   key. Save is metadata-only. Check connection and symbol lookup enqueue normal
   Runs; workers read fixed `/stock/market-status?exchange=US` and `/search` paths.
   A health receipt states which endpoint was checked, not that every symbol is
   entitled. Missing/rejected keys, rate limits and unsupported quotes are honest
   unavailable/misconfigured results. No automatic retries that consume credits.
2. Add reviewed provider/connector revision and symbol scope to MarketScope.
   Keep crypto defaults and baseline hashes unchanged. Stock symbol discovery
   uses an explicit company/symbol search with bounded selectable results;
   typing alone does not issue network calls. The user can review/override it.
   Activation and dispatch revalidate connector/revision/secret availability.
3. In the existing quote stage, fetch bounded quote/profile data per symbol and
   one market-status snapshot. Reuse the DNS-pinned public HTTP reader, verified
   TLS, host/redirect guards, deadline and cancellation polling. The key travels
   only in the fixed authentication header. Persist validated canonical subsets,
   never raw credential-bearing responses/URLs/errors. Reject credential echoes
   before creating artifacts; drop authentication on cross-origin redirects.
4. Parse JSON prices directly as Decimal, validate symbol/profile currency and
   provider timestamps. Closed-market/holiday snapshots retain their actual as-of
   time and appear as last known, not live. Permit a bounded seven-day source age
   while closed; require recent quotes for a regular open session. Stock defaults
   use a seven-day maximum comparison gap so an ordinary weekend does not reset
   the previous close. Explicit shorter gaps remain the user's choice. Zero,
   malformed, future, stale, revised or unsupported observations never manufacture
   an alert or silently replace an immutable baseline.
5. Persist currency, source timestamp kind, market-state timestamp and freshness
   metadata on observations, with an Alembic migration if the model is extended.
   Legacy observations remain readable. Generalize provenance checks and UI labels
   to source timestamps; do not relabel snapshots as actual exchange trades.
6. Reuse compare/notice/report/SMTP Runs and Task Stop. A provider-specific fixed
   stock-email template includes currency, source/as-of state and source link.
   Preserve crypto template/receipt identities and existing valid approvals.
   Canonical approval scopes omit newly absent optional stock fields so the new
   schema does not invalidate unchanged crypto grants. Changed feed/symbol/currency
   or delivery policy requires review; copies inherit no authorization.
7. Update factory, agent settings, conversation cards and results together. A
   natural-language stock request becomes a disabled, reviewable draft with stock
   intent rather than a Bitcoin watch. No model invents prices or recipients.
   Empty configuration gives a direct Settings link, not a fake working adapter.

## Verification

Normal tests use synthetic quote/profile/status bodies and temporary databases.
Cover exact decimal values, missing/invalid symbols and currencies, stale/future
quotes, provider-status age, closed sessions/weekends, correction/dedup/cooldown,
connector revision and credential redaction, permissions, Stop/recovery, old crypto
baselines and grants, and SMTP template/provenance isolation. Compiled desktop and
phone acceptance must exercise lookup/select/save/enable/results/failure paths.
Run full local gates and review the complete PR before merging to develop.

A real read needs the operator's own configured account and explicit opt-in. Real
external mail remains separately scoped; a fake provider or private SMTP sink is
not live market/account acceptance. No real Finnhub key or quote was used when
writing this plan and parser. Current production and backups remain recorded in
`data/acceptance/safety-redeploy-20261012/deployment.json`.


## Implementation checkpoint

The account adapter, queued check/search, stock scope and migration 0031, quote
workflow, source metadata, closed-session comparison, separate stock-email
template and shared desktop/phone controls were deployed in #344.
Focused fake-account/worker/SMTP and UI tests pass. Qualification and rollout
evidence is recorded under `data/acceptance/stock-price-agents-20261022`; only
executed checks in that evidence establish release readiness. No real finance
account was used. The first source profile supports only known NASDAQ/NYSE-family
USD listing labels; unknown exchanges fail closed instead of borrowing US hours.
