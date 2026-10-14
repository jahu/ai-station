import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";

export type ChatProviderInfo = {
  id: string;
  key: string;
  name: string;
  kind: string;
  location: "local" | "external";
  endpoint: string;
  default_model: string;
  enabled: boolean;
  builtin: boolean;
  status: string;
  error: string | null;
  secret_ref: string;
  secret_source: "none" | "env" | "stored";
  secret_present: boolean;
  models?: string[];
  updated_at?: string;
};

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function secretLabel(row: ChatProviderInfo) {
  if (row.secret_source === "none") return "No secret";
  if (!row.secret_present) return "Secret missing";
  return row.secret_source === "env" ? row.secret_ref : "Secret stored";
}

function ProviderCards({
  providers,
  removePending,
  onRemove,
}: {
  providers: ChatProviderInfo[];
  removePending: boolean;
  onRemove: (id: string, name: string) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    providers,
    (row) => row.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Chat providers
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a provider while the list is focused. Remove stays on
        the selected row. There is no inspectable provider Run.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {providers.map((row, i) => {
          const current = i === index;
          const shortId = row.id.slice(0, 8);
          return (
            <div key={row.id} {...itemProps(i, row.id)}>
              <div>
                <strong>{row.name}</strong>
                <p>
                  {row.location} · <span className="mono">{row.endpoint}</span>
                  {row.secret_ref ? ` · ${row.secret_ref}` : ""}
                </p>
              </div>
              <div className="row">
                <Badge
                  status={
                    row.secret_present || row.secret_source === "none"
                      ? row.enabled
                        ? "available"
                        : "unavailable"
                      : "unavailable"
                  }
                />
                <span className="muted">{secretLabel(row)}</span>
                {!row.builtin && (
                  <Button
                    variant="secondary"
                    tabIndex={current ? 0 : -1}
                    disabled={removePending}
                    aria-label={`Remove ${row.name} ${shortId}`}
                    onClick={() => onRemove(row.id, row.name)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function ChatProviders() {
  const cache = useQueryClient();
  const providers = useQuery({
    queryKey: ["chat-providers"],
    queryFn: () => api<ChatProviderInfo[]>("/chat/providers"),
  });
  const [secret, setSecret] = useState("");
  const create = useMutation({
    mutationFn: (body: unknown) =>
      api<ChatProviderInfo>("/chat/providers", json("POST", body)),
    onSuccess: () => {
      setSecret("");
      void cache.invalidateQueries({ queryKey: ["chat-providers"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      api(`/chat/providers/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      void cache.invalidateQueries({ queryKey: ["chat-providers"] }),
  });
  return (
    <section className="panel mt">
      <div className="panel-heading">
        <div>
          <h2>Chat providers</h2>
          <p className="muted">
            Explicit selection · secret references, never plaintext keys in URLs
            or API responses
          </p>
        </div>
      </div>
      <p className="muted">
        The built-in local provider follows <code>AI_STATION_LLM_*</code>. Extra
        OpenAI-compatible endpoints are selected per conversation. Paste a
        secret only to store it as a file reference; it is never shown again.
        Environment references use <code>env:NAME</code>. Missing secrets fail
        closed. Pixel vision is not enabled.
      </p>
      <ErrorNotice error={providers.error ?? create.error ?? remove.error} />
      {!!providers.data?.length && (
        <ProviderCards
          providers={providers.data}
          removePending={remove.isPending}
          onRemove={(id, name) => {
            if (
              window.confirm(
                `Remove ${name}? Conversations must use another provider first.`,
              )
            )
              remove.mutate(id);
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
            location: fields.get("location"),
            endpoint: fields.get("endpoint"),
            default_model: fields.get("default_model"),
            ...(secret
              ? { secret }
              : secretRef
                ? { secret_ref: secretRef }
                : {}),
          });
        }}
      >
        <h3>Add OpenAI-compatible provider</h3>
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
              placeholder="openai"
            />
          </label>
        </div>
        <div className="field-pair">
          <label>
            Location
            <select
              name="location"
              defaultValue="external"
              aria-label="Location"
            >
              <option value="external">External</option>
              <option value="local">Local private network</option>
            </select>
          </label>
          <label>
            Default model
            <input name="default_model" maxLength={200} />
          </label>
        </div>
        <label>
          Endpoint
          <input
            name="endpoint"
            required
            maxLength={500}
            placeholder="https://api.example.com/v1"
          />
        </label>
        <div className="field-pair">
          <label>
            Secret reference
            <input
              name="secret_ref"
              maxLength={200}
              placeholder="env:OPENAI_API_KEY"
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
          {create.isPending ? "Saving…" : "Add provider"}
        </Button>
      </form>
      <p className="muted">
        Open <Link to="/chat">Chat</Link> and choose the provider before
        sending. Normal tests never call cloud APIs.
      </p>
    </section>
  );
}
