import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";

type Scope = { connector_id: string; connector_revision: string };
type Connection = {
  id: string;
  name: string;
  kind: string;
  url: string;
  enabled: boolean;
  http_policy_revision?: string;
  secret_source?: string;
  secret_present?: boolean;
};
export default function HttpAgentScope({
  value,
  disabled,
  onChange,
}: {
  value: Scope | null;
  disabled: boolean;
  onChange: (value: Scope | null) => void;
}) {
  const query = useQuery({
    queryKey: ["connectors"],
    queryFn: () => api<Connection[]>("/connectors"),
  });
  const choices =
    query.data?.filter(
      (row) => row.kind === "http" && row.enabled && row.http_policy_revision,
    ) ?? [];
  const current = choices.find(
    (row) =>
      row.id === value?.connector_id &&
      row.http_policy_revision === value.connector_revision,
  );
  return (
    <div>
      <label>
        Reviewed HTTP connection
        <select
          aria-label="Reviewed HTTP connection"
          disabled={disabled || query.isPending}
          value={current?.id ?? ""}
          onChange={(event) => {
            const selected = choices.find(
              (row) => row.id === event.target.value,
            );
            onChange(
              selected
                ? {
                    connector_id: selected.id,
                    connector_revision: selected.http_policy_revision!,
                  }
                : null,
            );
          }}
        >
          <option value="">Choose a saved API connection</option>
          {choices.map((row) => (
            <option key={row.id} value={row.id}>
              {row.name} · {row.url}
            </option>
          ))}
        </select>
      </label>
      {current && (
        <p className="mono" aria-label="Reviewed API address">
          GET {current.url}
        </p>
      )}
      {current?.secret_source && current.secret_source !== "none" && (
        <p className="muted">
          {current.secret_present
            ? "Saved credential · supplied by AI Station, hidden from the model."
            : "Credential missing. Update this connection before running."}
        </p>
      )}
      {value && !query.isPending && !current && (
        <p className="notice" role="status">
          This connection changed or is unavailable. Review and select it again
          before running.
        </p>
      )}
      {!query.isPending && !query.error && !choices.length && (
        <p className="notice">
          Add an HTTP connection in Settings → Integrations first.
        </p>
      )}
      <p className="muted">
        Each execution reads this saved address. The response can feed a report
        or local data analysis. Changing its address or authentication requires
        a new review.
      </p>
      <Link className="text-link" to="/settings/integrations">
        Manage API connections
      </Link>
      <ErrorNotice error={query.error} />
    </div>
  );
}
