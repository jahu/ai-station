import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { DeliveryPreview, type Delivery } from "./EmailConnectors";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import type { MarketScope } from "./marketScope";

type Connection = {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  email_policy_revision: string;
  smtp?: { sender: string; allowed_recipients: string[] };
};
export type MarketEmailAuthorization = {
  id: string;
  valid: boolean;
  resolution: string;
  sender: string;
  recipients: string[];
  resolved_at: string | null;
  requested_at?: string;
  scope?: MarketScope;
};

function useConnections(enabled = true) {
  return useQuery({
    queryKey: ["connectors"],
    queryFn: () => api<Connection[]>("/connectors"),
    enabled,
  });
}

export function MarketEmailSettings({
  value,
  onChange,
}: {
  value: MarketScope;
  onChange: (value: MarketScope) => void;
}) {
  const connections = useConnections();
  const rows =
    connections.data?.filter((row) => row.kind === "email" && row.smtp) ?? [];
  const selected = rows.find((row) => row.id === value.email?.connector_id);
  const stale =
    value.email &&
    selected &&
    selected.email_policy_revision !== value.email.connector_revision;
  const select = (row?: Connection) =>
    onChange({
      ...value,
      email: row?.smtp
        ? {
            connector_id: row.id,
            connector_revision: row.email_policy_revision,
            recipients: row.smtp.allowed_recipients.slice(0, 1),
          }
        : null,
    });
  return (
    <section className="market-email-policy" aria-label="Price alert delivery">
      <h4>Alert delivery</h4>
      <p className="muted">
        Alerts always appear in AI Station. You can also send threshold alerts
        to your reviewed email addresses.
      </p>
      <label>
        Deliver alerts to
        <select
          aria-label="Deliver alerts to"
          value={value.email?.connector_id ?? ""}
          onChange={(event) =>
            select(rows.find((row) => row.id === event.target.value))
          }
        >
          <option value="">AI Station only</option>
          {value.email && !selected && (
            <option value={value.email.connector_id}>
              Unavailable saved connection
            </option>
          )}
          {rows.map((row) => (
            <option key={row.id} value={row.id} disabled={!row.enabled}>
              AI Station + email · {row.name}
              {row.enabled ? "" : " (disabled)"}
            </option>
          ))}
        </select>
      </label>
      {!rows.some((row) => row.enabled) && !connections.isPending && (
        <p className="muted">
          Connect a mail account in{" "}
          <Link to="/settings/integrations">Settings → Integrations</Link>, then
          return here.
        </p>
      )}
      {selected?.smtp && value.email && (
        <>
          <p className="muted">From {selected.smtp.sender}</p>
          {stale ? (
            <div className="notice">
              The mail settings changed. Review the sender and allowed
              recipients before saving a new scope.
              <Button
                type="button"
                variant="secondary"
                onClick={() => select(selected)}
              >
                Use current mail settings
              </Button>
            </div>
          ) : (
            <div
              role="group"
              aria-label="Price alert recipients"
              className="email-recipient-choices"
            >
              {selected.smtp.allowed_recipients.map((address) => (
                <label key={address} className="project-checkbox">
                  <input
                    type="checkbox"
                    checked={value.email!.recipients.includes(address)}
                    disabled={
                      (value.email!.recipients.includes(address) &&
                        value.email!.recipients.length === 1) ||
                      (!value.email!.recipients.includes(address) &&
                        value.email!.recipients.length >= 5)
                    }
                    onChange={(event) =>
                      onChange({
                        ...value,
                        email: {
                          ...value.email!,
                          recipients: event.target.checked
                            ? [...value.email!.recipients, address]
                            : value.email!.recipients.filter(
                                (item) => item !== address,
                              ),
                        },
                      })
                    }
                  />
                  {address}
                </label>
              ))}
            </div>
          )}
        </>
      )}
      <p className="muted">
        Saving sends nothing. Enabling asks you to approve automatic email for
        this exact price policy and recipient list.
      </p>
      <ErrorNotice error={connections.error} />
    </section>
  );
}

export function MarketEmailApproval({
  market,
  enabled,
  authorization,
  checked,
  onChange,
  onReadyChange,
}: {
  market?: MarketScope | null;
  enabled: boolean;
  authorization?: MarketEmailAuthorization | null;
  checked: boolean;
  onChange: (checked: boolean) => void;
  onReadyChange: (ready: boolean) => void;
}) {
  const connections = useConnections(!!market?.email);
  const scope = market?.email;
  const row = connections.data?.find(
    (item) => item.id === scope?.connector_id && item.kind === "email",
  );
  const ready =
    !!scope &&
    !!row?.enabled &&
    row.email_policy_revision === scope.connector_revision &&
    scope.recipients.length > 0 &&
    scope.recipients.every((address) =>
      row.smtp?.allowed_recipients.includes(address),
    );
  useEffect(() => {
    onReadyChange(ready);
  }, [onReadyChange, ready]);
  if (!scope) return null;
  return (
    <section
      className="market-email-consent"
      aria-label="Automatic price-alert email"
    >
      <h4>Email alerts</h4>
      <p>
        From{" "}
        <strong>
          {row?.smtp?.sender ?? authorization?.sender ?? "saved mail account"}
        </strong>{" "}
        to <strong>{scope.recipients.join(", ")}</strong>.
      </p>
      <p className="muted">
        Send when the{" "}
        {market!.direction === "both"
          ? "absolute"
          : market!.direction === "up"
            ? "upward"
            : "downward"}{" "}
        change reaches {market!.threshold_percent}%, at most once per instrument
        every {market!.cooldown_seconds / 60} minutes.
      </p>
      <details>
        <summary>What the email contains</summary>
        <p className="muted">
          A fixed price alert with the instrument, previous/current prices,
          percentage change, trade timestamps, public source and alert ID. No
          model-written text or conversation content is included. SMTP
          acceptance is recorded separately from inbox delivery.
        </p>
      </details>
      {authorization && (
        <details>
          <summary>Approval details</summary>
          <p className="muted">
            Status: {authorization.resolution}. Recorded{" "}
            {authorization.requested_at
              ? new Date(authorization.requested_at).toLocaleString()
              : "previously"}
            .
          </p>
          {authorization.scope && (
            <p className="muted">
              Approved threshold: {authorization.scope.threshold_percent}% ·{" "}
              {authorization.scope.direction}. Recipients:{" "}
              {authorization.recipients.join(", ")}.
            </p>
          )}
          <p className="muted">
            Approval <span className="mono">{authorization.id}</span>
          </p>
        </details>
      )}
      {enabled ? (
        <p className={authorization?.valid ? "muted" : "notice"}>
          {authorization?.valid
            ? "Automatic email approved. Pause this agent to revoke permission."
            : "Email approval needs review. Pause the agent, review mail settings, then enable it again."}
        </p>
      ) : (
        <>
          {!ready && !connections.isPending && (
            <p className="notice">
              Review the saved mail connection and recipients in this agent's
              settings before enabling email.
            </p>
          )}
          <label className="project-checkbox">
            <input
              type="checkbox"
              checked={checked && ready}
              disabled={!ready}
              onChange={(event) => onChange(event.target.checked)}
            />
            I allow this agent to send these price alerts automatically to the
            addresses above.
          </label>
        </>
      )}
      <ErrorNotice error={connections.error} />
    </section>
  );
}

export function AgentMarketEmailHistory({
  agentId,
  runs,
  title = "Price-alert email",
}: {
  agentId: string;
  runs: Run[];
  title?: string;
}) {
  const updates = runs
    .filter((run) => run.executor_type === "email_send")
    .map((run) => `${run.id}:${run.status}`)
    .join(",");
  const preparationFailures = runs.filter(
    (run) =>
      (run.metadata?.result_email as { state?: string } | undefined)?.state ===
      "preparation_failed",
  );
  const history = useQuery({
    queryKey: ["agent-email-deliveries", agentId, updates],
    queryFn: () => api<Delivery[]>(`/email/deliveries?agent_id=${agentId}`),
    refetchInterval: (query) =>
      query.state.data?.some(
        (row) =>
          !["succeeded", "failed", "canceled", "interrupted"].includes(
            row.run.status,
          ),
      )
        ? 2000
        : false,
  });
  return history.data?.length || history.error || preparationFailures.length ? (
    <section className="panel email-connector" aria-label={`${title} history`}>
      <h3>{title}</h3>
      {preparationFailures.map((run) => (
        <p key={run.id} className="notice">
          The result is ready, but its email could not be prepared.{" "}
          <Link to={`/runs/${run.id}`}>Inspect result</Link>.
        </p>
      ))}
      <ErrorNotice error={history.error} />
      {history.data?.map((row) => (
        <DeliveryPreview
          key={row.id}
          delivery={row}
          refresh={() => {
            void history.refetch();
          }}
        />
      ))}
    </section>
  ) : null;
}

export function AgentMarketRunStop({
  agentId,
  runs,
  subject = "price check",
}: {
  agentId: string;
  runs: Run[];
  subject?: string;
}) {
  const cache = useQueryClient();
  const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
  const active = (taskId: string) =>
    runs.filter((run) => run.task_id === taskId && !terminal.has(run.status));
  const parent = runs.find(
    (run) =>
      run.executor_type === "agent_workflow" && active(run.task_id).length > 0,
  );
  const cancel = useMutation({
    mutationFn: (runId: string) =>
      api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["agent", agentId] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      void cache.invalidateQueries({
        queryKey: ["agent-email-deliveries", agentId],
      });
    },
  });
  if (!parent) return null;
  const stopping = active(parent.task_id).every(
    (run) => run.status === "cancel_requested",
  );
  return (
    <>
      <Button
        type="button"
        variant="secondary"
        disabled={cancel.isPending || stopping}
        onClick={() => cancel.mutate(parent.id)}
      >
        {cancel.isPending || stopping
          ? `Stopping ${subject}…`
          : `Stop current ${subject}`}
      </Button>
      <ErrorNotice error={cancel.error} />
    </>
  );
}
