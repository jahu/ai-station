import { useState } from "react";
import { Link } from "react-router-dom";
import type { Run } from "../api";
import { Button } from "../components/ui/button";

const OTHER_OUTPUTS = new Set([
  "coding_local",
  "coding_cursor",
  "coding_codex",
  "python_data",
  "create_media",
  "market_watch",
]);

export function reportAlertsSupported(tools: string[]) {
  return !tools.some((name) => OTHER_OUTPUTS.has(name));
}

type FieldProps = {
  value?: string;
  tools: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  tabIndex?: number;
};

export function ReportAlertField({
  value = "",
  tools,
  onChange,
  disabled,
  tabIndex,
}: FieldProps) {
  const supported = reportAlertsSupported(tools);
  if (!supported && !value) return null;
  return (
    <div className="agent-wide">
      <label>
        Only notify when (optional)
        <textarea
          value={value}
          maxLength={1500}
          rows={3}
          disabled={disabled}
          tabIndex={tabIndex}
          placeholder="A significant new local model release fits this workstation. Skip repeated findings."
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
      <p className="muted">
        Every report stays in history. This criterion gates success notices and
        result email, using the previous successful report with the same
        settings. Failure and approval notices keep their own settings. Leave
        blank to notify about every successful result in your selected channels.
      </p>
      {!supported && (
        <p className="notice" role="alert">
          Criteria apply to report agents. Explicitly clear this field before
          changing to code, data, media or price-watch output.
        </p>
      )}
    </div>
  );
}

type EditorProps = Omit<FieldProps, "onChange"> & {
  onSave: (value: string) => void;
};

export function ReportAlertEditor(props: EditorProps) {
  return <ReportAlertEditorForm key={props.value ?? ""} {...props} />;
}

function ReportAlertEditorForm({ value, onSave, ...props }: EditorProps) {
  const [draft, setDraft] = useState(value ?? "");
  if (!draft && !reportAlertsSupported(props.tools)) return null;
  return (
    <div>
      <ReportAlertField {...props} value={draft} onChange={setDraft} />
      <Button
        type="button"
        variant="secondary"
        tabIndex={props.tabIndex}
        disabled={props.disabled || draft === (value ?? "")}
        onClick={() => onSave(draft)}
      >
        Save notification criterion
      </Button>
    </div>
  );
}

export function ReportAlertResult({ runs }: { runs: Run[] }) {
  const latest = runs
    .filter((run) => run.executor_type === "agent")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const value = latest?.metadata?.report_alert as
    | {
        state?: string;
        criterion?: string;
        notify?: boolean;
        reason?: string;
        previous_report?: { run_id: string } | null;
      }
    | undefined;
  if (!latest || !value) return null;
  const completed = latest.status === "succeeded" && value.state === "checked";
  const label = completed
    ? value.notify
      ? "Matching finding"
      : "No alert needed"
    : latest.status === "failed" || latest.status === "interrupted"
      ? "Alert check needs attention"
      : latest.status === "canceled"
        ? "Alert check canceled"
        : "Checking notification criterion…";
  return (
    <section className="agent-data-result" aria-label="Notification decision">
      <h3>{label}</h3>
      <p>
        {completed
          ? value.reason
          : "The report remains available. No success notification has been sent."}
      </p>
      {completed && !value.notify && (
        <p className="muted">
          No success notice or email was queued for this report.
        </p>
      )}
      <details>
        <summary>Notification criterion &amp; comparison</summary>
        <p>{value.criterion}</p>
        {value.previous_report ? (
          <Link
            className="text-link"
            to={`/runs/${value.previous_report.run_id}`}
          >
            Compared with the previous report
          </Link>
        ) : (
          <p className="muted">No previous compatible report was available.</p>
        )}
      </details>
      <Link className="text-link" to={`/runs/${latest.id}`}>
        Inspect this report &amp; alert check
      </Link>
    </section>
  );
}
