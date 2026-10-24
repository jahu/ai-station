import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

const DATA_FORMATS = [
  { kind: "csv", label: "CSV table" },
  { kind: "xlsx", label: "Excel workbook" },
  { kind: "png", label: "PNG chart" },
  { kind: "text", label: "Text report" },
] as const;

export type ResultEmailScope = {
  connector_id: string;
  connector_revision: string;
  recipients: string[];
  mode: "review" | "automatic";
  content: "report" | "summary";
  subject_prefix: string;
  attachment_kinds?: ("csv" | "xlsx" | "png" | "text")[];
};
export type ResultEmailAuthorization = {
  valid: boolean;
  mode: "review" | "automatic";
  reason?: string;
  ready?: boolean;
  sender?: string;
};
type Connection = {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  email_policy_revision: string;
  smtp?: { sender: string; allowed_recipients: string[] };
};

export function ResultEmailSettings(props: {
  value?: ResultEmailScope | null;
  onChange: (value: ResultEmailScope | null) => void;
  summaryOnly?: boolean;
  dataFiles?: boolean;
  disabled?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>
        Email delivery ·{" "}
        {props.value
          ? props.value.mode === "review"
            ? "Review each message"
            : "Automatic"
          : "AI Station only"}
      </summary>
      {expanded && <ResultEmailFields {...props} />}
    </details>
  );
}

function ResultEmailFields({
  value,
  onChange,
  summaryOnly = false,
  dataFiles = false,
  disabled = false,
}: {
  value?: ResultEmailScope | null;
  onChange: (value: ResultEmailScope | null) => void;
  summaryOnly?: boolean;
  dataFiles?: boolean;
  disabled?: boolean;
}) {
  const connections = useQuery({
    queryKey: ["connectors"],
    queryFn: async () => {
      const result = await api<Connection[]>("/connectors");
      if (!Array.isArray(result))
        throw new Error(
          "Mail account list is unavailable. Refresh and try again.",
        );
      return result;
    },
  });
  const rows = (connections.data ?? []).filter(
    (row) => row.kind === "email" && row.smtp,
  );
  const selected = rows.find((row) => row.id === value?.connector_id);
  const stale =
    !!value &&
    !!selected &&
    value.connector_revision !== selected.email_policy_revision;
  const select = (row?: Connection) =>
    onChange(
      row?.smtp
        ? {
            connector_id: row.id,
            connector_revision: row.email_policy_revision,
            recipients: row.smtp.allowed_recipients.slice(0, 1),
            mode: value?.mode ?? "review",
            content: summaryOnly ? "summary" : (value?.content ?? "report"),
            subject_prefix: value?.subject_prefix ?? "AI Station",
            ...(value?.attachment_kinds?.length
              ? { attachment_kinds: value.attachment_kinds }
              : {}),
          }
        : null,
    );
  return (
    <section className="market-email-policy" aria-label="Result email settings">
      <h4>Email delivery</h4>
      <p className="muted">
        Send a finished result to your saved addresses. Setup sends nothing.
      </p>
      <fieldset disabled={disabled}>
        <label>
          Deliver results to
          <select
            aria-label="Deliver results to"
            value={value?.connector_id ?? ""}
            onChange={(event) =>
              select(rows.find((row) => row.id === event.target.value))
            }
          >
            <option value="">AI Station only</option>
            {value && !selected && (
              <option value={value.connector_id}>
                Unavailable saved connection
              </option>
            )}
            {rows.map((row) => (
              <option key={row.id} value={row.id} disabled={!row.enabled}>
                {row.name}
                {row.enabled ? "" : " (disabled)"}
              </option>
            ))}
          </select>
        </label>
        {value && (
          <>
            <label>
              Sending mode
              <select
                aria-label="Sending mode"
                value={value.mode}
                onChange={(event) =>
                  onChange({
                    ...value,
                    mode: event.target.value as ResultEmailScope["mode"],
                  })
                }
              >
                <option value="review">Review each message</option>
                <option value="automatic">Automatic after completion</option>
              </select>
            </label>
            <label>
              Email content
              <select
                aria-label="Email content"
                value={value.content}
                onChange={(event) =>
                  onChange({
                    ...value,
                    content: event.target.value as ResultEmailScope["content"],
                  })
                }
              >
                <option value="report" disabled={summaryOnly}>
                  Completed report text
                </option>
                <option value="summary">
                  {value.attachment_kinds?.length
                    ? "Result summary body"
                    : "Result summary only"}
                </option>
              </select>
            </label>
            {(dataFiles || !!value.attachment_kinds?.length) && (
              <fieldset
                aria-label="Generated file attachments"
                className="email-recipient-choices"
              >
                <legend>Generated file attachments · optional</legend>
                {DATA_FORMATS.map(({ kind, label }) => (
                  <label className="project-checkbox" key={kind}>
                    <input
                      type="checkbox"
                      aria-label={`Attach ${label}`}
                      checked={value.attachment_kinds?.includes(kind) ?? false}
                      disabled={
                        !dataFiles && !value.attachment_kinds?.includes(kind)
                      }
                      onChange={(event) => {
                        const selected = new Set(value.attachment_kinds ?? []);
                        if (event.target.checked) selected.add(kind);
                        else selected.delete(kind);
                        const kinds = DATA_FORMATS.map(
                          (item) => item.kind,
                        ).filter((item) => selected.has(item));
                        onChange({
                          ...value,
                          attachment_kinds: kinds.length ? kinds : undefined,
                        });
                      }}
                    />
                    {label}
                  </label>
                ))}
                <p className="muted">
                  Selected formats are created with each result. Up to four
                  files, 4 MiB each and 16 MiB combined. Generated values will
                  leave this workstation; original uploads and scripts are not
                  attached.
                </p>
              </fieldset>
            )}
            <label>
              Subject prefix
              <input
                aria-label="Subject prefix"
                maxLength={80}
                required
                value={value.subject_prefix}
                onChange={(event) =>
                  onChange({ ...value, subject_prefix: event.target.value })
                }
              />
            </label>
            {selected?.smtp && (
              <>
                <p className="muted">From {selected.smtp.sender}</p>
                {stale ? (
                  <div className="notice">
                    Mail settings changed. Review the account and recipients.
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
                    aria-label="Result email recipients"
                    className="email-recipient-choices"
                  >
                    {selected.smtp.allowed_recipients.map((address) => (
                      <label key={address} className="project-checkbox">
                        <input
                          type="checkbox"
                          checked={value.recipients.includes(address)}
                          disabled={
                            value.recipients.includes(address)
                              ? value.recipients.length === 1
                              : value.recipients.length >= 5
                          }
                          onChange={(event) =>
                            onChange({
                              ...value,
                              recipients: event.target.checked
                                ? [...value.recipients, address]
                                : value.recipients.filter(
                                    (item) => item !== address,
                                  ),
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
              {value.content === "report"
                ? "Includes the saved report text (up to 16,000 characters, with an excerpt notice for longer reports)."
                : "Includes only completion status and saved result IDs."}{" "}
              {value.attachment_kinds?.length
                ? "Selected generated files are also attached."
                : "No files are attached."}{" "}
              Automatic sending requires confirmation when you enable the agent.
            </p>
          </>
        )}
      </fieldset>
      {disabled && (
        <p className="muted">Pause the agent before changing email delivery.</p>
      )}
      {!connections.isPending && !rows.some((row) => row.enabled) && (
        <p className="muted">
          Add a mail account in{" "}
          <Link to="/settings/integrations">Settings → Integrations</Link>.
        </p>
      )}
      <ErrorNotice error={connections.error} />
    </section>
  );
}

export function ResultEmailEditor({
  value,
  onSave,
  summaryOnly,
  dataFiles = false,
  disabled,
}: {
  value?: ResultEmailScope | null;
  onSave: (scope: ResultEmailScope | null) => void;
  summaryOnly: boolean;
  dataFiles?: boolean;
  disabled: boolean;
}) {
  const [draft, setDraft] = useState(value ?? null);
  return (
    <div>
      <ResultEmailSettings
        value={draft}
        onChange={setDraft}
        summaryOnly={summaryOnly}
        dataFiles={dataFiles}
        disabled={disabled}
      />
      <Button
        type="button"
        variant="secondary"
        disabled={
          disabled || JSON.stringify(draft) === JSON.stringify(value ?? null)
        }
        onClick={() => onSave(draft)}
      >
        Save email delivery
      </Button>
    </div>
  );
}

export function ResultEmailApproval({
  scope,
  enabled,
  authorization,
  checked,
  onChange,
}: {
  scope?: ResultEmailScope | null;
  enabled: boolean;
  authorization?: ResultEmailAuthorization | null;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  if (!scope) return null;
  return (
    <section
      className="market-email-consent"
      aria-label="Result email approval"
    >
      <h4>
        {scope.mode === "automatic"
          ? "Automatic result email"
          : "Review result email"}
      </h4>
      <p>
        {authorization?.sender && (
          <>
            From <strong>{authorization.sender}</strong>.{" "}
          </>
        )}
        To <strong>{scope.recipients.join(", ")}</strong>.{" "}
        {scope.content === "report"
          ? "The actual completed report text will leave this workstation."
          : scope.attachment_kinds?.length
            ? "The email body contains completion status and result IDs."
            : "Only completion status and result IDs will leave this workstation."}
      </p>
      {!!scope.attachment_kinds?.length && (
        <p>
          Generated files will also leave this workstation:{" "}
          <strong>
            {DATA_FORMATS.filter((item) =>
              scope.attachment_kinds?.includes(item.kind),
            )
              .map((item) => item.label)
              .join(", ")}
          </strong>
          . This selection is included in your delivery approval.
        </p>
      )}
      {authorization?.ready === false && (
        <p className="notice">{authorization.reason}</p>
      )}
      {scope.mode === "review" ? (
        <p className="muted">
          Every finished message waits here for your review. Nothing is sent
          until you approve that message.
        </p>
      ) : enabled ? (
        <p className={authorization?.valid ? "muted" : "notice"}>
          {authorization?.valid
            ? "Automatic delivery approved. Pause the agent to revoke it."
            : (authorization?.reason ??
              "Pause, review the saved definition and enable again to approve email.")}
        </p>
      ) : (
        <label className="project-checkbox">
          <input
            type="checkbox"
            disabled={authorization?.ready === false}
            checked={checked}
            onChange={(event) => onChange(event.target.checked)}
          />
          I allow automatic delivery of completed results for this saved
          definition to these addresses.
        </label>
      )}
    </section>
  );
}
