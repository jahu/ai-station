import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";

type Scope = { connector_id: string; repository: string };
type Repository = {
  id: string;
  name: string;
  kind: string;
  repository: string;
  enabled: boolean;
};
export default function GithubAgentScope({
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
    queryFn: () => api<Repository[]>("/connectors"),
  });
  const choices =
    query.data?.filter((row) => row.kind === "github" && row.enabled) ?? [];
  const current = choices.find(
    (row) =>
      row.id === value?.connector_id && row.repository === value.repository,
  );
  return (
    <div>
      <label>
        Reviewed GitHub repository
        <select
          aria-label="Reviewed GitHub repository"
          disabled={disabled || query.isPending}
          value={current?.id ?? ""}
          onChange={(event) => {
            const selected = choices.find(
              (row) => row.id === event.target.value,
            );
            onChange(
              selected
                ? { connector_id: selected.id, repository: selected.repository }
                : null,
            );
          }}
        >
          <option value="">Choose a connected repository</option>
          {choices.map((row) => (
            <option value={row.id} key={row.id}>
              {row.name} · {row.repository}
            </option>
          ))}
        </select>
      </label>
      {value && !query.isPending && !current && (
        <p className="notice">
          The reviewed target {value.repository} is unavailable or changed.
          Select it again before running.
        </p>
      )}
      <p className="muted">
        Each run reads this repository's open issues and PR titles through your
        host GitHub login, then prepares a local-model report. A changed or
        disconnected target stops the read. Requires at least 70 seconds maximum
        runtime.
      </p>
      <Link className="text-link" to="/settings/integrations">
        Manage connected repositories
      </Link>
      <ErrorNotice error={query.error} />
    </div>
  );
}
