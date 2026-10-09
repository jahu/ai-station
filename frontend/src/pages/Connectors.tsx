import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

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
      <div className="diagnostic-list">
        {kinds.data
          ?.filter((item) => !item.operational)
          .map((item) => (
            <div key={item.kind}>
              <div>
                <strong>{item.kind}</strong>
                <p>{item.summary}</p>
              </div>
              <Badge status="unavailable" />
            </div>
          ))}
        {connectors.data?.map((row) => (
          <div key={row.id}>
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
                <Link className="text-link" to={`/runs/${row.last_run_id}`}>
                  Open last check →
                </Link>
              )}
              <Button
                variant="secondary"
                disabled={check.isPending || !row.enabled}
                onClick={() => check.mutate(row.id)}
              >
                Check GET
              </Button>
              <Button
                variant="secondary"
                disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm(`Remove ${row.name}?`))
                    remove.mutate(row.id);
                }}
              >
                Remove
              </Button>
            </div>
          </div>
        ))}
      </div>
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
