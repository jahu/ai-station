# Scheduled price observations

Implementation in progress. This slice adds a reviewed, deterministic market
agent, reusing durable schedules, Tasks, child Runs, Artifacts and in-app notices.
It neither trades nor sends email. Scoped SMTP delivery and a stock-data provider
remain separate follow-up work; do not advertise them as operational.

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
not a claim of a fixed-period return. First observations establish a baseline;
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
