import { useId, useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";

type ConnectorInfo = {
  id: string;
  key: string;
  name: string;
  kind: string;
  url: string;
  method: string;
  status: string;
  health: string;
  enabled: boolean;
  last_run_id: string | null;
  secret_ref: string;
  secret_source: "none" | "env" | "stored";
  secret_present: boolean;
};
type KindInfo = {
  kind: string;
  operational: boolean;
  summary: string;
};

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function secretLabel(row: ConnectorInfo) {
  if (row.secret_source === "none") return "No secret";
  if (!row.secret_present) return "Secret missing";
  return row.secret_source === "env" ? row.secret_ref : "Secret stored";
}

function UnavailableCards({ items }: { items: KindInfo[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.kind,
  );
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Unavailable adapters
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an unpublished adapter while the list is focused.
        These kinds stay unavailable. There is no inspectable adapter Run.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {items.map((item, i) => (
          <div
            key={item.kind}
            aria-label={`Adapter ${item.kind}`}
            {...itemProps(i, item.kind)}
          >
            <div>
              <strong>{item.kind}</strong>
              <p>{item.summary}</p>
            </div>
            <Badge status="unavailable" />
          </div>
        ))}
      </div>
    </section>
  );
}

function ConnectorCards({
  connectors,
  checkPending,
  removePending,
  onCheck,
  onRemove,
}: {
  connectors: ConnectorInfo[];
  checkPending: boolean;
  removePending: boolean;
  onCheck: (id: string) => void;
  onRemove: (id: string, name: string) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    connectors,
    (row) => row.id,
  );
  const selected = connectors[index];
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.last_run_id) {
      event.preventDefault();
      navigate(`/runs/${selected.last_run_id}`);
    }
  };
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Named connectors
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a connector while the list is focused. Enter inspects
        its last check when one exists. Check GET and Remove stay on the
        selected row.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {connectors.map((row, i) => {
          const current = i === index;
          const shortId = row.id.slice(0, 8);
          return (
            <div key={row.id} {...itemProps(i, row.id)}>
              <div>
                <strong>{row.name}</strong>
                <p>
                  {row.kind} GET · <span className="mono">{row.url}</span>
                </p>
              </div>
              <div className="row">
                <Badge
                  status={row.health === "healthy" ? "available" : row.status}
                />
                <span className="muted">{secretLabel(row)}</span>
                {row.last_run_id && (
                  <Link
                    className="text-link"
                    to={`/runs/${row.last_run_id}`}
                    tabIndex={current ? 0 : -1}
                    aria-label={`Inspect ${row.name} ${shortId}`}
                  >
                    Open last check →
                  </Link>
                )}
                <Button
                  variant="secondary"
                  tabIndex={current ? 0 : -1}
                  disabled={checkPending || !row.enabled}
                  aria-label={`Check GET ${row.name} ${shortId}`}
                  onClick={() => onCheck(row.id)}
                >
                  Check GET
                </Button>
                <Button
                  variant="secondary"
                  tabIndex={current ? 0 : -1}
                  disabled={removePending}
                  aria-label={`Remove ${row.name} ${shortId}`}
                  onClick={() => onRemove(row.id, row.name)}
                >
                  Remove
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function Connectors() {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const connectors = useQuery({
    queryKey: ["connectors"],
    queryFn: () => api<ConnectorInfo[]>("/connectors"),
  });
  const kinds = useQuery({
    queryKey: ["connector-kinds"],
    queryFn: () => api<KindInfo[]>("/connectors/kinds"),
  });
  const [secret, setSecret] = useState("");
  const create = useMutation({
    mutationFn: (body: unknown) =>
      api<ConnectorInfo>("/connectors", json("POST", body)),
    onSuccess: () => {
      setSecret("");
      void cache.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
  const check = useMutation({
    mutationFn: (id: string) =>
      api<{ id: string }>(`/connectors/${id}/check`, { method: "POST" }),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["connectors"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${run.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/connectors/${id}`, { method: "DELETE" }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["connectors"] }),
  });
  const unavailable = kinds.data?.filter((item) => !item.operational) ?? [];
  return (
    <section className="panel mt">
      <div className="panel-heading">
        <div>
          <h2>Connectors</h2>
          <p className="muted">
            Named HTTP GET endpoints · secret references, never plaintext keys
          </p>
        </div>
      </div>
      <p className="muted">
        Only reviewed public <code>http</code>/<code>https</code> GET is
        operational. Browser, GitHub, email, calendar and social adapters are
        listed so they stay visibly unavailable. A health check is an ordinary
        Run with a JSON artifact. Paste a secret only to store it; it is never
        shown again.
      </p>
      <ErrorNotice
        error={
          connectors.error ??
          kinds.error ??
          create.error ??
          check.error ??
          remove.error
        }
      />
      {unavailable.length > 0 && <UnavailableCards items={unavailable} />}
      {!!connectors.data?.length && (
        <ConnectorCards
          connectors={connectors.data}
          checkPending={check.isPending}
          removePending={remove.isPending}
          onCheck={(id) => check.mutate(id)}
          onRemove={(id, name) => {
            if (window.confirm(`Remove ${name}?`)) remove.mutate(id);
          }}
        />
      )}
      <form
        className="image-form mt"
        onSubmit={(event) => {
          event.preventDefault();
          const fields = new FormData(event.currentTarget);
          const secretRef = String(fields.get("secret_ref") ?? "").trim();
          create.mutate({
            key: fields.get("key"),
            name: fields.get("name"),
            url: fields.get("url"),
            ...(secret
              ? { secret }
              : secretRef
                ? { secret_ref: secretRef }
                : {}),
          });
        }}
      >
        <h3>Add HTTP GET connector</h3>
        <div className="field-pair">
          <label>
            Name
            <input name="name" required maxLength={200} />
          </label>
          <label>
            Key
            <input
              name="key"
              required
              maxLength={80}
              pattern="[a-z][a-z0-9-]{1,78}"
              placeholder="status-page"
            />
          </label>
        </div>
        <label>
          Public URL
          <input
            name="url"
            required
            maxLength={2000}
            placeholder="https://example.com/status"
          />
        </label>
        <div className="field-pair">
          <label>
            Secret reference
            <input
              name="secret_ref"
              maxLength={200}
              placeholder="env:STATUS_TOKEN"
              autoComplete="off"
            />
          </label>
          <label>
            Store secret
            <input
              type="password"
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              maxLength={4096}
              autoComplete="new-password"
              placeholder="Write-only; never displayed"
            />
          </label>
        </div>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Saving…" : "Add connector"}
        </Button>
      </form>
    </section>
  );
}
