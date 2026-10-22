import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Send, ShieldCheck } from "lucide-react";
import { api, type Run } from "../api";
import { randomId } from "../lib/random-id";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

export type SMTP = {
  host: string;
  transport: "ssl" | "starttls";
  username: string;
  sender: string;
  allowed_recipients: string[];
};
export type EmailConnector = {
  id: string;
  key: string;
  name: string;
  smtp: SMTP;
  updated_at: string;
  enabled: boolean;
  health: string;
  secret_present: boolean;
  last_run_id: string | null;
};
type Delivery = {
  id: string;
  state: string;
  reason: string;
  payload: {
    sender: string;
    recipients: string[];
    subject: string;
    body: string;
  };
  accepted_recipients: string[];
  refused_recipients: string[];
  run: Run;
};
const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);

function MailSettings({
  row,
  onDone,
}: {
  row?: EmailConnector;
  onDone: () => void;
}) {
  const cache = useQueryClient();
  const [password, setPassword] = useState("");
  const [clear, setClear] = useState(false);
  const save = useMutation({
    mutationFn: (body: unknown) =>
      api(
        row ? `/connectors/${row.id}` : "/connectors",
        json(row ? "PATCH" : "POST", body),
      ),
    onSuccess: () => {
      setPassword("");
      void cache.invalidateQueries({ queryKey: ["connectors"] });
      onDone();
    },
  });
  return (
    <form
      className="email-settings"
      onSubmit={(event) => {
        event.preventDefault();
        const fields = new FormData(event.currentTarget);
        const smtp: SMTP = {
          host: String(fields.get("host")),
          transport: String(fields.get("transport")) as SMTP["transport"],
          username: clear ? "" : String(fields.get("username") ?? ""),
          sender: String(fields.get("sender")),
          allowed_recipients: String(fields.get("recipients"))
            .split(/[,\n]/)
            .map((v) => v.trim())
            .filter(Boolean),
        };
        save.mutate({
          name: String(fields.get("name")),
          smtp,
          ...(row
            ? {
                expected_updated_at: row.updated_at,
                ...(clear
                  ? { clear_secret: true }
                  : password
                    ? { secret: password }
                    : {}),
              }
            : {
                key: "email-" + randomId().slice(0, 8),
                kind: "email",
                ...(password ? { secret: password } : {}),
              }),
        });
      }}
    >
      <fieldset disabled={save.isPending}>
        <legend>{row ? "Mail settings" : "Connect email"}</legend>
        <div className="field-pair">
          <label>
            Name
            <input
              name="name"
              required
              maxLength={200}
              defaultValue={row?.name ?? "My email"}
            />
          </label>
          <label>
            Sender address
            <input
              name="sender"
              type="email"
              required
              maxLength={254}
              defaultValue={row?.smtp.sender ?? ""}
              placeholder="you@example.com"
            />
          </label>
          <label>
            SMTP server
            <input
              name="host"
              required
              maxLength={253}
              defaultValue={row?.smtp.host ?? ""}
              placeholder="smtp.example.com"
            />
          </label>
          <label>
            Secure connection
            <select
              name="transport"
              defaultValue={row?.smtp.transport ?? "ssl"}
            >
              <option value="ssl">SSL / TLS · port 465</option>
              <option value="starttls">STARTTLS · port 587</option>
            </select>
          </label>
        </div>
        <details open={!!row?.smtp.username || !row}>
          <summary>Authentication</summary>
          <div className="field-pair">
            <label>
              Username
              <input
                name="username"
                autoComplete="username"
                disabled={clear}
                defaultValue={row?.smtp.username ?? ""}
                maxLength={254}
              />
            </label>
            <label>
              {row?.secret_present
                ? "Replace password (optional)"
                : "App password"}
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={clear}
                autoComplete="new-password"
                maxLength={4096}
              />
            </label>
          </div>
          <p className="muted">
            Use your mail provider's SMTP app password. Stored credentials are
            never displayed or sent to a model.
          </p>
          {row?.secret_present && (
            <label className="project-checkbox">
              <input
                type="checkbox"
                checked={clear}
                onChange={(e) => setClear(e.target.checked)}
              />
              Remove saved credential and username
            </label>
          )}
        </details>
        <label>
          Allowed recipients
          <textarea
            name="recipients"
            rows={2}
            required
            defaultValue={row?.smtp.allowed_recipients.join("\n") ?? ""}
            placeholder="One address per line, up to 10"
          />
        </label>
        <p className="muted">
          Only these addresses can receive messages. Saving and checking the
          connection never sends mail.
        </p>
        <div className="row">
          <Button type="submit">
            {save.isPending
              ? "Saving…"
              : row
                ? "Save mail settings"
                : "Save email connection"}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </fieldset>
      <ErrorNotice error={save.error} />
    </form>
  );
}

function DeliveryPreview({
  delivery,
  refresh,
}: {
  delivery: Delivery;
  refresh: () => void;
}) {
  const approval = useMutation({
    mutationFn: (resolution: "granted" | "denied") =>
      api(`/runs/${delivery.run.id}/approval`, json("POST", { resolution })),
    onSuccess: refresh,
  });
  const stop = useMutation({
    mutationFn: () =>
      api(`/runs/${delivery.run.id}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  const stateLabel: Record<string, string> = {
    prepared: "Review before sending",
    sending: "Submitting to mail server…",
    accepted: "Accepted by mail server",
    accepted_partial: "Some recipients were refused",
    unknown: "Acceptance unknown — inspect before resending",
    failed_before_send: "Not sent",
    failed_before_acceptance: "Refused by mail server",
    canceled: "Canceled",
  };
  return (
    <details
      className="email-preview"
      open={!terminal.has(delivery.run.status) || delivery.state === "unknown"}
    >
      <summary>
        {delivery.payload.subject}{" "}
        <span className="muted">
          · {stateLabel[delivery.state] ?? delivery.state}
        </span>
      </summary>
      <dl className="email-envelope">
        <div>
          <dt>From</dt>
          <dd>{delivery.payload.sender}</dd>
        </div>
        <div>
          <dt>To</dt>
          <dd>{delivery.payload.recipients.join(", ")}</dd>
        </div>
      </dl>
      <pre className="email-body">{delivery.payload.body}</pre>
      {delivery.reason && <p className="muted">{delivery.reason}</p>}
      {delivery.accepted_recipients.length > 0 && (
        <p>Server accepted: {delivery.accepted_recipients.join(", ")}</p>
      )}
      {delivery.refused_recipients.length > 0 && (
        <p>Refused: {delivery.refused_recipients.join(", ")}</p>
      )}
      <div className="row">
        {delivery.run.status === "waiting_for_approval" && (
          <>
            <Button
              type="button"
              disabled={approval.isPending}
              onClick={() => approval.mutate("granted")}
            >
              <Send size={15} />
              Approve and send
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={approval.isPending}
              onClick={() => approval.mutate("denied")}
            >
              Do not send
            </Button>
          </>
        )}
        {!terminal.has(delivery.run.status) &&
          delivery.run.status !== "waiting_for_approval" && (
            <Button
              type="button"
              variant="secondary"
              disabled={stop.isPending}
              onClick={() => stop.mutate()}
            >
              Stop submission
            </Button>
          )}
        <Link to={`/runs/${delivery.run.id}`}>Inspect delivery</Link>
      </div>
      <ErrorNotice error={approval.error ?? stop.error} />
    </details>
  );
}

function MailCard({ row }: { row: EmailConnector }) {
  const cache = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [composing, setComposing] = useState(false);
  const [recipients, setRecipients] = useState<string[]>(
    row.smtp.allowed_recipients.slice(0, 1),
  );
  const request = useRef<{ body: string; id: string } | null>(null);
  const history = useQuery({
    queryKey: ["email-deliveries", row.id],
    queryFn: () => api<Delivery[]>(`/email/deliveries?connector_id=${row.id}`),
    refetchInterval: (q) =>
      q.state.data?.some((d) => !terminal.has(d.run.status)) ? 2000 : false,
  });
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["email-deliveries", row.id] });
    void cache.invalidateQueries({ queryKey: ["connectors"] });
  };
  const check = useMutation({
    mutationFn: () => api(`/connectors/${row.id}/check`, { method: "POST" }),
    onSuccess: refresh,
  });
  const preview = useMutation({
    mutationFn: (values: { subject: string; body: string }) => {
      const body = JSON.stringify({
        ...values,
        recipients,
        expected_updated_at: row.updated_at,
      });
      if (request.current?.body !== body)
        request.current = { body, id: randomId() };
      return api(
        `/email/connectors/${row.id}/drafts`,
        json("POST", {
          ...JSON.parse(body),
          client_request_id: request.current.id,
        }),
      );
    },
    onSuccess: () => {
      request.current = null;
      setComposing(false);
      refresh();
    },
  });
  const active =
    history.data?.some((d) => !terminal.has(d.run.status)) ?? false;
  return (
    <article
      className="content-panel email-connector"
      aria-label={`Email ${row.name}`}
    >
      <div className="row spread">
        <div>
          <h3>
            <Mail size={19} /> {row.name}
          </h3>
          <p className="muted">
            {row.smtp.sender} · {row.smtp.host}
          </p>
        </div>
        <span className="chip">
          {row.health === "healthy"
            ? "Connection verified"
            : row.health === "unhealthy"
              ? "Check connection"
              : "Not checked"}
        </span>
      </div>
      <div className="row">
        <Button
          variant="secondary"
          type="button"
          disabled={
            check.isPending ||
            active ||
            (row.last_run_id !== null &&
              row.health === "unknown" &&
              !row.enabled)
          }
          onClick={() => check.mutate()}
        >
          <ShieldCheck size={15} />
          Check connection
        </Button>
        <Button
          type="button"
          disabled={!row.enabled || composing}
          onClick={() => setComposing(true)}
        >
          Prepare a message
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={active}
          onClick={() => setEditing(!editing)}
        >
          Mail settings
        </Button>
        {row.last_run_id && (
          <Link to={`/runs/${row.last_run_id}`}>Connection details</Link>
        )}
      </div>
      {editing && <MailSettings row={row} onDone={() => setEditing(false)} />}
      {composing && (
        <form
          className="email-compose"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            preview.mutate({
              subject: String(data.get("subject")),
              body: String(data.get("body")),
            });
          }}
        >
          <fieldset disabled={preview.isPending}>
            <legend>Prepare a message</legend>
            <div
              className="email-recipient-choices"
              role="group"
              aria-label="Message recipients"
            >
              {row.smtp.allowed_recipients.map((address) => (
                <label className="project-checkbox" key={address}>
                  <input
                    type="checkbox"
                    checked={recipients.includes(address)}
                    disabled={
                      !recipients.includes(address) && recipients.length >= 5
                    }
                    onChange={(e) =>
                      setRecipients(
                        e.target.checked
                          ? [...recipients, address]
                          : recipients.filter((v) => v !== address),
                      )
                    }
                  />
                  {address}
                </label>
              ))}
            </div>
            <label>
              Subject
              <input
                name="subject"
                required
                maxLength={200}
                defaultValue="AI Station connection test"
              />
            </label>
            <label>
              Message
              <textarea
                name="body"
                rows={4}
                required
                maxLength={16000}
                defaultValue="This is a reviewed test message from AI Station."
              />
            </label>
            <p className="muted">
              Next: review the complete message and explicitly approve sending.
              Nothing is sent by preparing this preview.
            </p>
            <div className="row">
              <Button type="submit" disabled={!recipients.length}>
                Prepare preview
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setComposing(false)}
              >
                Cancel
              </Button>
            </div>
          </fieldset>
        </form>
      )}
      <ErrorNotice error={check.error ?? preview.error ?? history.error} />
      {!!history.data?.length && (
        <section
          aria-label={`Message history ${row.name}`}
          className="email-history"
        >
          <h4>Message history</h4>
          {history.data.map((d) => (
            <DeliveryPreview key={d.id} delivery={d} refresh={refresh} />
          ))}
        </section>
      )}
    </article>
  );
}

export function EmailConnectors({ rows }: { rows: EmailConnector[] }) {
  const [adding, setAdding] = useState(false);
  return (
    <section className="email-connectors" aria-label="Email connections">
      <div className="row spread">
        <div>
          <h3>Email</h3>
          <p className="muted">
            Connect your mail provider and review every message before sending.
            Automatic agent email is not enabled yet.
          </p>
        </div>
        <Button
          variant="secondary"
          type="button"
          onClick={() => setAdding(!adding)}
        >
          Connect email
        </Button>
      </div>
      {adding && <MailSettings onDone={() => setAdding(false)} />}
      {rows.map((row) => (
        <MailCard key={row.id} row={row} />
      ))}
    </section>
  );
}
