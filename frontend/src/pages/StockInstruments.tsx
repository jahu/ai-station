import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { api, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { stockJson, stockTerminal, type StockFeed } from "./stockFeed";
import type { MarketScope } from "./marketScope";

type SearchRun = Run & {
  metadata?: {
    market_feed?: {
      query: string;
      symbols: { symbol: string; name: string; type: string }[];
      truncated: boolean;
      source_url: string;
      fetched_at: string;
    };
  };
};

export default function StockInstruments({
  value,
  onChange,
}: {
  value: MarketScope;
  onChange: (value: MarketScope) => void;
}) {
  const cache = useQueryClient();
  const connections = useQuery({
    queryKey: ["connectors"],
    queryFn: () => api<StockFeed[]>("/connectors"),
  });
  const accounts =
    connections.data?.filter(
      (row) => row.kind === "market_data" && row.market_provider === "finnhub",
    ) ?? [];
  const account = accounts.find((row) => row.id === value.feed?.connector_id);
  const stale =
    !!value.feed &&
    !!account &&
    value.feed.connector_revision !== account.market_policy_revision;
  const [query, setQuery] = useState("");
  const [manual, setManual] = useState("");
  const [lookup, setLookup] = useState<{
    id: string;
    connector: string;
    revision: string;
  } | null>(null);
  const search = useMutation({
    mutationFn: (request: {
      connector: string;
      revision: string;
      query: string;
    }) =>
      api<Run>(
        `/market-feeds/${request.connector}/search`,
        stockJson("POST", {
          connector_revision: request.revision,
          query: request.query,
        }),
      ),
    onSuccess: (run, request) => {
      setLookup({
        id: run.id,
        connector: request.connector,
        revision: request.revision,
      });
      void cache.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const sameScope =
    !!lookup &&
    lookup.connector === value.feed?.connector_id &&
    lookup.revision === value.feed.connector_revision &&
    !stale;
  const run = useQuery({
    queryKey: ["stock-symbol-search", lookup?.id],
    queryFn: () => api<SearchRun>(`/runs/${lookup?.id}`),
    enabled: sameScope,
    refetchInterval: (state) =>
      state.state.data && !stockTerminal.has(state.state.data.status)
        ? 1000
        : false,
  });
  const active =
    sameScope && (!run.data || !stockTerminal.has(run.data.status));
  const stop = useMutation({
    mutationFn: () => api(`/runs/${lookup?.id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["stock-symbol-search", lookup?.id],
      });
    },
  });
  const result =
    sameScope && run.data?.status === "succeeded"
      ? run.data.metadata?.market_feed
      : undefined;
  const add = (symbol: string) => {
    if (!value.instruments.includes(symbol) && value.instruments.length < 3)
      onChange({
        ...value,
        instruments: [...value.instruments, symbol].sort(),
      });
  };
  const validManual =
    /^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$/.test(manual) && manual.length <= 15;
  return (
    <section className="stock-instruments" aria-label="Stock selection">
      <label>
        Stock-data account
        <select
          aria-label="Stock-data account"
          value={value.feed?.connector_id ?? ""}
          disabled={search.isPending || active}
          onChange={(event) => {
            const selected = accounts.find(
              (row) => row.id === event.target.value,
            );
            onChange({
              ...value,
              feed: selected?.market_policy_revision
                ? {
                    connector_id: selected.id,
                    connector_revision: selected.market_policy_revision,
                  }
                : null,
            });
          }}
        >
          <option value="">Choose an account</option>
          {value.feed && !account && (
            <option value={value.feed.connector_id}>
              Unavailable saved account
            </option>
          )}
          {accounts.map((row) => (
            <option
              key={row.id}
              value={row.id}
              disabled={!row.enabled || !row.secret_present}
            >
              {row.name}
              {!row.enabled
                ? " (disabled)"
                : !row.secret_present
                  ? " (key missing)"
                  : ""}
            </option>
          ))}
        </select>
      </label>
      {connections.isPending && (
        <p role="status" className="muted">
          Loading stock-data accounts…
        </p>
      )}
      {!accounts.some((row) => row.enabled && row.secret_present) &&
        !connections.isPending && (
          <p className="muted">
            Connect your Finnhub account in{" "}
            <Link to="/settings/integrations">Settings → Integrations</Link>,
            then choose up to three USD stock symbols.
          </p>
        )}
      {stale && (
        <div className="stock-account-review" role="alert">
          <p>
            Account settings changed. Review them before using this account
            again; saving starts a new price baseline.
          </p>
          <Button
            type="button"
            variant="secondary"
            disabled={!account?.enabled || !account.secret_present}
            onClick={() => {
              if (account?.market_policy_revision)
                onChange({
                  ...value,
                  feed: {
                    connector_id: account.id,
                    connector_revision: account.market_policy_revision,
                  },
                });
            }}
          >
            Use current account settings
          </Button>
        </div>
      )}
      <div className="stock-symbol-search">
        <label>
          Find a company or symbol
          <input
            type="search"
            maxLength={80}
            placeholder="e.g. Apple or AAPL"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (
                  query.trim() &&
                  value.feed &&
                  account?.enabled &&
                  account.secret_present &&
                  !stale &&
                  !active &&
                  !search.isPending
                )
                  search.mutate({
                    connector: value.feed.connector_id,
                    revision: value.feed.connector_revision,
                    query: query.trim(),
                  });
              }
            }}
          />
        </label>
        <Button
          type="button"
          variant="secondary"
          disabled={
            !query.trim() ||
            !value.feed ||
            !account?.enabled ||
            !account.secret_present ||
            stale ||
            active ||
            search.isPending
          }
          onClick={() => {
            if (value.feed)
              search.mutate({
                connector: value.feed.connector_id,
                revision: value.feed.connector_revision,
                query: query.trim(),
              });
          }}
        >
          <Search size={15} />
          {search.isPending || active ? "Searching…" : "Find symbols"}
        </Button>
        {active && (
          <Button
            type="button"
            variant="ghost"
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            Stop lookup
          </Button>
        )}
      </div>
      <ErrorNotice
        error={connections.error ?? search.error ?? run.error ?? stop.error}
      />
      {sameScope && run.data?.error_message && (
        <p role="alert">{run.data.error_message}</p>
      )}
      {sameScope && run.data?.status === "canceled" && (
        <p role="status" className="muted">
          Symbol lookup stopped.
        </p>
      )}
      {result && (
        <div aria-label="Matching stock symbols">
          <p className="muted">Results for “{result.query}”</p>
          {!result.symbols.length && (
            <p>
              No matching supported symbols. Try a company name or exact symbol.
            </p>
          )}
          <ul className="stock-symbol-results">
            {result.symbols.map((item) => (
              <li key={item.symbol}>
                <div>
                  <strong>{item.symbol}</strong>
                  <span>{item.name}</span>
                  <small className="muted">{item.type}</small>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={
                    value.instruments.includes(item.symbol) ||
                    value.instruments.length >= 3
                  }
                  onClick={() => add(item.symbol)}
                  aria-label={`Add ${item.symbol}`}
                >
                  {value.instruments.includes(item.symbol) ? "Selected" : "Add"}
                </Button>
              </li>
            ))}
          </ul>
          {result.truncated && (
            <p className="muted">
              Showing a limited result set. Refine your search if the company is
              missing.
            </p>
          )}
          <p className="muted">
            A search result does not confirm quote access or USD currency; these
            are checked when the agent reads its first price.
          </p>
        </div>
      )}
      {sameScope && lookup && (
        <Link className="text-link" to={`/runs/${lookup.id}`}>
          Inspect symbol lookup
        </Link>
      )}
      <div className="stock-selected" role="group" aria-label="Selected stocks">
        {value.instruments.map((symbol) => (
          <span key={symbol}>
            <strong>{symbol}</strong>
            <Button
              type="button"
              variant="ghost"
              aria-label={`Remove ${symbol}`}
              onClick={() =>
                onChange({
                  ...value,
                  instruments: value.instruments.filter(
                    (item) => item !== symbol,
                  ),
                })
              }
            >
              <X size={14} />
            </Button>
          </span>
        ))}
      </div>
      <p className="muted">
        {value.instruments.length} / 3 stocks selected · USD quotes
      </p>
      <details>
        <summary>Enter a symbol manually</summary>
        <div className="stock-symbol-search">
          <label>
            Stock symbol
            <input
              value={manual}
              maxLength={15}
              placeholder="AAPL"
              onChange={(event) => setManual(event.target.value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  if (
                    validManual &&
                    value.instruments.length < 3 &&
                    !value.instruments.includes(manual)
                  ) {
                    add(manual);
                    setManual("");
                  }
                }
              }}
            />
          </label>
          <Button
            type="button"
            variant="secondary"
            disabled={
              !validManual ||
              value.instruments.includes(manual) ||
              value.instruments.length >= 3
            }
            onClick={() => {
              add(manual);
              setManual("");
            }}
          >
            Add symbol
          </Button>
        </div>
      </details>
    </section>
  );
}
