import { MarketEmailSettings } from "./AgentMarketEmail";
import { useState } from "react";
import { Button } from "../components/ui/button";

import { DEFAULT_MARKET, type MarketScope } from "./marketScope";
import StockInstruments from "./StockInstruments";

export default function AgentMarketScope({
  value,
  disabled,
  onChange,
}: {
  value?: MarketScope | null;
  disabled?: boolean;
  onChange: (scope: MarketScope) => void;
}) {
  const current = value ?? DEFAULT_MARKET;
  return (
    <fieldset className="agent-wide agent-market-policy" disabled={disabled}>
      <legend>Price watch</legend>
      <p className="muted">
        Calculations run locally without a model or GPU. Choose your price
        source, instruments, threshold and alert delivery below.
      </p>
      <label>
        Price source
        <select
          aria-label="Price source"
          value={current.provider}
          onChange={(event) =>
            onChange({
              ...current,
              provider: event.target.value as MarketScope["provider"],
              feed: null,
              instruments: event.target.value === "finnhub" ? [] : ["BTC-USD"],
              comparison_window_seconds:
                event.target.value === "finnhub" ? 604800 : 172800,
            })
          }
        >
          <option value="coinbase_exchange">Crypto · Coinbase</option>
          <option value="finnhub">Stocks · Finnhub</option>
        </select>
      </label>
      {current.provider === "finnhub" ? (
        <StockInstruments value={current} onChange={onChange} />
      ) : (
        <>
          <p className="muted">
            Coinbase last-trade prices. No account needed.
          </p>
          <div
            className="market-instruments"
            role="group"
            aria-label="Instruments"
          >
            {["BTC-USD", "BTC-EUR", "ETH-USD", "ETH-EUR"].map((pair) => (
              <label className="project-checkbox" key={pair}>
                <input
                  type="checkbox"
                  checked={current.instruments.includes(pair)}
                  disabled={
                    current.instruments.includes(pair)
                      ? current.instruments.length === 1
                      : current.instruments.length >= 3
                  }
                  onChange={(e) =>
                    onChange({
                      ...current,
                      instruments: e.target.checked
                        ? [...current.instruments, pair].sort()
                        : current.instruments.filter((item) => item !== pair),
                    })
                  }
                />
                {pair.replace("-", " / ")}
              </label>
            ))}
          </div>
        </>
      )}
      <div className="market-policy-grid">
        <label>
          Alert when change reaches (%)
          <input
            type="number"
            min="0.0001"
            max="100"
            step="0.0001"
            required
            value={current.threshold_percent}
            onChange={(e) =>
              onChange({ ...current, threshold_percent: e.target.value })
            }
          />
        </label>
        <label>
          Direction
          <select
            aria-label="Direction"
            value={current.direction}
            onChange={(e) =>
              onChange({
                ...current,
                direction: e.target.value as MarketScope["direction"],
              })
            }
          >
            <option value="both">Up or down</option>
            <option value="up">Price increases</option>
            <option value="down">Price decreases</option>
          </select>
        </label>
        <label>
          Maximum observation gap (minutes)
          <input
            type="number"
            min="1"
            max="43200"
            step="1"
            required
            value={current.comparison_window_seconds / 60}
            onChange={(e) =>
              onChange({
                ...current,
                comparison_window_seconds: Number(e.target.value) * 60,
              })
            }
          />
        </label>
        <label>
          Minimum time between alerts (minutes)
          <input
            type="number"
            min="1"
            max="43200"
            step="1"
            required
            value={current.cooldown_seconds / 60}
            onChange={(e) =>
              onChange({
                ...current,
                cooldown_seconds: Number(e.target.value) * 60,
              })
            }
          />
        </label>
      </div>
      <MarketEmailSettings value={current} onChange={onChange} />
      <p className="muted">
        Compares with the previous valid observation within this gap. The first
        reading sets a baseline. Stale or repeated source observations never
        trigger alerts. Choose when to check under Schedule. Changing this
        policy starts a new baseline. Saving a changed price or delivery policy
        pauses the agent for review.
      </p>
      {current.provider === "finnhub" && (
        <p className="muted">
          Regular-session quotes must be recent. When the market is closed, the
          last known quote can be up to seven days old and keeps its actual
          provider timestamp. The default seven-day comparison gap covers a
          normal weekend. No trades are placed.
        </p>
      )}
    </fieldset>
  );
}

export function AgentMarketEditor({
  value,
  disabled,
  onSave,
}: {
  value?: MarketScope | null;
  disabled?: boolean;
  onSave: (scope: MarketScope) => void;
}) {
  const [draft, setDraft] = useState(value ?? DEFAULT_MARKET);
  const changed =
    JSON.stringify(draft) !== JSON.stringify(value ?? DEFAULT_MARKET);
  const valid =
    /^\d{1,3}(?:\.\d{1,4})?$/.test(draft.threshold_percent) &&
    Number(draft.threshold_percent) > 0 &&
    Number(draft.threshold_percent) <= 100 &&
    (draft.provider === "coinbase_exchange" ||
      (!!draft.feed && draft.instruments.length > 0)) &&
    (!draft.email || draft.email.recipients.length > 0) &&
    [draft.comparison_window_seconds, draft.cooldown_seconds].every(
      (seconds) =>
        Number.isInteger(seconds) && seconds >= 60 && seconds <= 2592000,
    );
  return (
    <div>
      <AgentMarketScope value={draft} disabled={disabled} onChange={setDraft} />
      <Button
        type="button"
        disabled={disabled || !changed || !valid}
        onClick={() => onSave(draft)}
      >
        Save price watch
      </Button>
    </div>
  );
}
