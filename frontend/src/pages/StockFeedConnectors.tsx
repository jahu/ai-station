import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LineChart, ShieldCheck } from "lucide-react";
import { api, type Run } from "../api";
import { randomId } from "../lib/random-id";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

import { stockJson, stockTerminal, type StockFeed } from "./stockFeed";

function FeedSettings({
  row,
  onDone,
}: {
  row?: StockFeed;
  onDone: () => void;
}) {
  const cache = useQueryClient();
  const [secret, setSecret] = useState("");
  const save = useMutation({
    mutationFn: (body: unknown) =>
      api(
        row ? `/connectors/${row.id}` : "/connectors",
        stockJson(row ? "PATCH" : "POST", body),
      ),
    onSuccess: () => {
      setSecret("");
      void cache.invalidateQueries({ queryKey: ["connectors"] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      onDone();
    },
  });
  return (
    <form
      className="email-settings"
      onSubmit={(event) => {
        event.preventDefault();
        const fields = new FormData(event.currentTarget);
        const enabled = fields.get("enabled") === "on";
        save.mutate({
          name: String(fields.get("name")),
          ...(row
            ? {
                expected_updated_at: row.updated_at,
                ...(enabled !== row.enabled ? { enabled } : {}),
              }
            : {
                key: "stocks-" + randomId().slice(0, 8),
                kind: "market_data",
                market_provider: "finnhub",
                enabled,
              }),
          ...(secret ? { secret } : {}),
        });
      }}
    >
      <fieldset disabled={save.isPending}>
        <legend>{row ? "Stock-data settings" : "Connect Finnhub"}</legend>
        <div className="field-pair">
          <label>
            Account name
            <input
              name="name"
              required
              maxLength={200}
              defaultValue={row?.name ?? "My stock data"}
            />
          </label>
          <label>
            Finnhub API key
            <input
              type="password"
              autoComplete="off"
              required={!row?.secret_present}
              minLength={8}
              maxLength={512}
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              placeholder={
                row?.secret_present
                  ? "Saved · leave blank to keep"
                  : "Your account API key"
              }
            />
          </label>
        </div>
        <label className="project-checkbox">
          <input
            name="enabled"
            type="checkbox"
            defaultChecked={row?.enabled ?? true}
          />
          Account enabled
        </label>
        <p className="muted">
          The key stays write-only. Saving makes no requests. Account or key
          changes require reviewing affected price agents again.
        </p>
        <ErrorNotice error={save.error} />
        <div className="row">
          <Button type="submit">
            {save.isPending ? "Saving…" : "Save stock-data account"}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </fieldset>
    </form>
  );
}

function FeedCard({ row }: { row: StockFeed }) {
  const cache = useQueryClient();
  const [editing, setEditing] = useState(false);
  const last = useQuery({
    queryKey: ["stock-feed-check", row.last_run_id],
    queryFn: () => api<Run>(`/runs/${row.last_run_id}`),
    enabled: !!row.last_run_id,
    refetchInterval: (query) =>
      query.state.data && !stockTerminal.has(query.state.data.status)
        ? 1500
        : false,
  });
  const lastStatus = last.data?.status;
  useEffect(() => {
    if (lastStatus && stockTerminal.has(lastStatus))
      void cache.invalidateQueries({ queryKey: ["connectors"] });
  }, [lastStatus, cache]);
  const check = useMutation({
    mutationFn: () => api(`/connectors/${row.id}/check`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/connectors/${row.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
  const stop = useMutation({
    mutationFn: () =>
      api(`/runs/${row.last_run_id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["stock-feed-check", row.last_run_id],
      });
      void cache.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
  const active =
    row.status === "checking" ||
    (!!last.data && !stockTerminal.has(last.data.status));
  return (
    <article
      className="email-connector"
      aria-label={`Stock-data account ${row.name}`}
    >
      <div className="row">
        <h3>{row.name}</h3>
        <span className="muted">Finnhub · US stocks · USD</span>
      </div>
      <p className="muted">
        {!row.enabled
          ? "Disabled"
          : !row.secret_present
            ? "Credential missing"
            : active
              ? "Checking market-status endpoint…"
              : row.health === "healthy"
                ? "Market-status endpoint verified"
                : row.health === "unhealthy"
                  ? "Last check failed"
                  : "Not checked"}
      </p>
      <ErrorNotice
        error={check.error ?? remove.error ?? stop.error ?? last.error}
      />
      {last.data?.error_message && (
        <p role="alert">{last.data.error_message}</p>
      )}
      <div className="row">
        <Button
          type="button"
          variant="secondary"
          disabled={
            check.isPending || active || !row.enabled || !row.secret_present
          }
          onClick={() => check.mutate()}
        >
          <ShieldCheck size={15} />
          Check stock account
        </Button>
        {active && row.last_run_id && (
          <Button
            type="button"
            variant="secondary"
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            Stop check
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          disabled={active || remove.isPending}
          onClick={() => setEditing(!editing)}
        >
          Account settings
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={active || remove.isPending}
          onClick={() => {
            if (
              window.confirm(
                `Remove ${row.name} and its saved credential? Price history is preserved.`,
              )
            )
              remove.mutate();
          }}
        >
          Remove stock account
        </Button>
        {row.last_run_id && (
          <Link to={`/runs/${row.last_run_id}`}>Connection details</Link>
        )}
      </div>
      {editing && <FeedSettings row={row} onDone={() => setEditing(false)} />}
    </article>
  );
}

export function StockFeedConnectors({ rows }: { rows: StockFeed[] }) {
  const [adding, setAdding] = useState(false);
  return (
    <section className="email-connectors" aria-label="Stock-data accounts">
      <div className="row">
        <LineChart size={20} />
        <h3>Stock prices</h3>
        <Button
          type="button"
          variant="secondary"
          disabled={adding}
          onClick={() => setAdding(true)}
        >
          Connect stock data
        </Button>
      </div>
      <p className="muted">
        Connect your Finnhub account, then choose companies in an agent’s Price
        watch settings. Symbol access and rate limits depend on your
        subscription. This reads quotes; it does not trade.
      </p>
      {adding && <FeedSettings onDone={() => setAdding(false)} />}
      {!rows.length && !adding && (
        <p className="muted">
          No account connected. Existing cryptocurrency watches keep using
          Coinbase without a key.
        </p>
      )}
      {rows.map((row) => (
        <FeedCard key={row.id} row={row} />
      ))}
    </section>
  );
}
