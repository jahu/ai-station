import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Github, RefreshCw, ExternalLink } from "lucide-react";
import { api } from "../api";
import { randomId } from "../lib/random-id";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

type Item = {
  number: number;
  title: string;
  url: string;
  author: string;
  draft?: boolean;
};
type Connector = {
  id: string;
  name: string;
  repository: string;
  status: string;
  last_run_id: string | null;
  enabled: boolean;
};
type Snapshot = {
  captured_at: string;
  artifact_id: string;
  project: {
    name: string;
    description: string;
    url: string;
    private: boolean;
    default_branch: string;
  };
  issues: Item[];
  pull_requests: Item[];
};

function RepositoryCard({ row }: { row: Connector }) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["github-snapshot", row.id, row.last_run_id, row.status],
    placeholderData: (previous) => previous,
    queryFn: () =>
      api<{
        connector: Connector;
        snapshot: Snapshot | null;
        refresh_error?: string;
      }>(`/connectors/${row.id}/snapshot`),
    refetchInterval: row.status === "checking" ? 2000 : false,
  });
  const refresh = useMutation({
    mutationFn: () => api(`/connectors/${row.id}/check`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["connectors"] });
      void cache.invalidateQueries({ queryKey: ["github-snapshot", row.id] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/connectors/${row.id}`, { method: "DELETE" }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["connectors"] }),
  });
  const snapshot = query.data?.snapshot;
  return (
    <article
      className="content-panel github-repository-card"
      aria-label={`GitHub ${row.repository}`}
    >
      <div className="row spread">
        <div className="row">
          <Github size={20} aria-hidden="true" />
          <div>
            <strong>{row.name}</strong>
            <p className="muted mono">{row.repository}</p>
          </div>
        </div>
        <Badge
          status={
            row.status === "checking"
              ? "running"
              : row.status === "ready"
                ? "available"
                : row.status
          }
        />
      </div>
      {snapshot ? (
        <>
          {snapshot.project.description && (
            <p>{snapshot.project.description}</p>
          )}
          <p className="muted">
            {snapshot.project.private
              ? "Private repository"
              : "Public repository"}{" "}
            · {snapshot.project.default_branch} · Updated{" "}
            {new Date(snapshot.captured_at).toLocaleString()}
          </p>
          <div className="github-repository-lists">
            {(
              [
                ["Open issues", snapshot.issues],
                ["Open pull requests", snapshot.pull_requests],
              ] as const
            ).map(([label, items]) => (
              <section key={label} aria-label={`${label} ${row.repository}`}>
                <h4>{label}</h4>
                {items.length ? (
                  <ul className="github-entry-list">
                    {items.map((item) => (
                      <li key={item.number}>
                        <a
                          className="text-link"
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          #{item.number} {item.title}
                        </a>
                        {item.draft ? (
                          <span className="muted"> · Draft</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">None in this snapshot.</p>
                )}
              </section>
            ))}
          </div>
          <p className="muted">Latest 30 entries per list · Read only</p>
        </>
      ) : (
        <p className="muted">
          Refresh to read repository details, open issues and pull requests
          using your existing host GitHub login.
        </p>
      )}
      {query.data?.refresh_error && (
        <p className="notice" role="alert">
          {query.data.refresh_error}
        </p>
      )}
      <ErrorNotice error={query.error ?? refresh.error ?? remove.error} />
      <div className="github-repository-actions">
        <Button
          variant="secondary"
          onClick={() => refresh.mutate()}
          disabled={
            !row.enabled || row.status === "checking" || refresh.isPending
          }
        >
          <RefreshCw size={14} aria-hidden="true" />
          {row.status === "checking" ? "Refreshing…" : "Refresh repository"}
        </Button>
        <Button variant="ghost" asChild>
          <a
            href={`https://github.com/${row.repository}`}
            target="_blank"
            rel="noreferrer"
          >
            Open GitHub <ExternalLink size={14} aria-hidden="true" />
          </a>
        </Button>
        {row.last_run_id && (
          <Link className="text-link" to={`/runs/${row.last_run_id}`}>
            Inspect refresh
          </Link>
        )}
        {snapshot && (
          <a
            className="text-link"
            href={`/api/artifacts/${snapshot.artifact_id}/file`}
            target="_blank"
            rel="noreferrer"
          >
            Download snapshot
          </a>
        )}
        <Button
          variant="ghost"
          disabled={row.status === "checking" || remove.isPending}
          onClick={() => {
            if (
              window.confirm(
                `Disconnect ${row.repository}? Saved Runs and snapshots remain. The GitHub repository is unchanged.`,
              )
            )
              remove.mutate();
          }}
        >
          Disconnect
        </Button>
      </div>
    </article>
  );
}

export function GithubConnectors({ rows }: { rows: Connector[] }) {
  const cache = useQueryClient();
  const [repository, setRepository] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api("/connectors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "github",
          repository: repository.trim(),
          name: repository.trim(),
          key: `github-${randomId()}`,
        }),
      }),
    onSuccess: () => {
      setRepository("");
      void cache.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
  return (
    <section className="github-connectors mt" aria-label="GitHub repositories">
      <div className="panel-heading">
        <div>
          <h3 className="row">
            <Github size={18} aria-hidden="true" /> GitHub repositories
          </h3>
          <p className="muted">
            Your projects, issues and pull requests in one place. Uses the
            host's existing gh login; no token to copy.
          </p>
        </div>
      </div>
      {rows.map((row) => (
        <RepositoryCard row={row} key={row.id} />
      ))}
      <form
        className="image-form github-connect-form"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label>
          Repository
          <input
            aria-label="GitHub repository"
            value={repository}
            onChange={(event) => setRepository(event.target.value)}
            placeholder="owner/repository"
            required
            maxLength={140}
          />
        </label>
        <Button type="submit" disabled={create.isPending || !repository.trim()}>
          {create.isPending ? "Connecting…" : "Connect repository"}
        </Button>
      </form>
      <ErrorNotice error={create.error} />
    </section>
  );
}
