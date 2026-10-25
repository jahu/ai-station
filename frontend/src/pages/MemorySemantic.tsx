import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, LoaderCircle, Search, Sparkles } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import "./MemorySemantic.css";

type Hit = { id: string; content: string; scope: string; score: number };
type Setup = {
  configured: boolean;
  backend?: string;
  revision?: number;
  endpoint: string;
  model: string;
  dimension: number | null;
  indexed_count: number;
  memory_count: number;
  local_model?: {
    id: string;
    name: string;
    size_bytes: number;
    installed: boolean;
    available: boolean;
  };
  prepare_run?: Run | null;
  index_run?: Run | null;
  health_run?: Run | null;
};
const active = (run?: Run | null) =>
  !!run &&
  !["succeeded", "failed", "canceled", "interrupted"].includes(run.status);
const json = (body: unknown, method = "POST") => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function MemorySemantic({
  scope = "",
  target = "",
}: {
  scope?: string;
  target?: string;
}) {
  const cache = useQueryClient();
  const [consent, setConsent] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<{ id: string; scope: string }>();
  const [endpoint, setEndpoint] = useState("");
  const [model, setModel] = useState("");
  const scopeKey = `${scope}:${target}`;
  const setup = useQuery({
    queryKey: ["memory-embeddings"],
    queryFn: () => api<Setup>("/memory/embeddings/setup"),
    refetchInterval: (q) =>
      [
        q.state.data?.prepare_run,
        q.state.data?.index_run,
        q.state.data?.health_run,
      ].some(active)
        ? 1000
        : false,
  });
  const current = setup.data;
  const operation = useMutation({
    mutationFn: ({
      path,
      body,
      method,
    }: {
      path: string;
      body: unknown;
      method?: string;
      searchScope?: string;
    }) => api<Run | Setup>(`/memory/embeddings/${path}`, json(body, method)),
    onSuccess: (result, variables) => {
      void cache.invalidateQueries({ queryKey: ["memory-embeddings"] });
      if ("id" in result)
        setSelected({
          id: result.id,
          scope: variables.searchScope ?? "",
        });
    },
  });
  const watched = useQuery({
    queryKey: ["run", selected?.id],
    queryFn: () => api<Run>(`/runs/${selected?.id}`),
    enabled: !!selected?.id,
    refetchInterval: (q) =>
      active(q.state.data) || !q.state.data ? 500 : false,
  });
  useEffect(() => {
    if (watched.data && !active(watched.data))
      void cache.invalidateQueries({ queryKey: ["memory-embeddings"] });
  }, [cache, watched.data]);
  const busy =
    operation.isPending ||
    [current?.prepare_run, current?.index_run, current?.health_run].some(
      active,
    );
  const running = [
    watched.data,
    current?.prepare_run,
    current?.index_run,
    current?.health_run,
  ].find(active);
  const last =
    running ??
    [
      watched.data,
      current?.prepare_run,
      current?.index_run,
      current?.health_run,
    ]
      .filter((run): run is Run => !!run)
      .sort((a, b) =>
        (b.created_at ?? "").localeCompare(a.created_at ?? ""),
      )[0];
  const local = current?.local_model;
  const localMode = current?.backend === "local_cpu";
  const ready = !!current?.configured && (!localMode || local?.installed);
  const missing = Math.max(
    0,
    (current?.memory_count ?? 0) - (current?.indexed_count ?? 0),
  );
  const results = watched.data?.metadata?.results as Hit[] | undefined;
  const inScope = selected?.scope === scopeKey;
  const progress = running?.metadata?.embedding_progress as
    { indexed: number; skipped_current: number; total: number } | undefined;
  const download = running?.metadata?.embedding_download as
    | { file: string; received_bytes: number; expected_bytes: number }
    | undefined;
  const invoke = (path: string, body: unknown = {}) =>
    operation.mutate({
      path,
      body,
      searchScope: path === "search" ? scopeKey : "",
    });
  return (
    <section className="panel memory-semantic" aria-label="Semantic memory">
      <div className="memory-semantic-heading">
        <div>
          <h2>
            <Sparkles size={18} aria-hidden="true" /> Semantic search
          </h2>
          <p className="muted">
            Find memories by meaning, even when the words differ.
          </p>
        </div>
        <span className="memory-semantic-device">
          <Cpu size={14} aria-hidden="true" />{" "}
          {localMode || !current?.configured ? "LOCAL · CPU" : "LOCAL ENDPOINT"}
        </span>
      </div>
      {!ready && (
        <div className="memory-semantic-setup">
          <strong>
            {localMode
              ? "Local model needs attention"
              : "Set up semantic memory"}
          </strong>
          <p className="muted">
            {local?.name ?? "Multilingual E5 Small"} supports multilingual
            search. Full-text search remains available.
          </p>
          {local && !local.installed && (
            <label className="memory-semantic-consent">
              <input
                type="checkbox"
                checked={consent}
                disabled={busy}
                onChange={(e) => setConsent(e.target.checked)}
              />
              Download the local model and tokenizer (
              {Math.ceil(local.size_bytes / 1024 ** 2)} MiB). Memory content
              stays on this machine.
            </label>
          )}
          {local && (
            <Button
              disabled={
                busy || !local.available || (!local.installed && !consent)
              }
              onClick={() =>
                invoke("prepare", {
                  expected_revision: current?.revision ?? 0,
                  model_id: local.id,
                  confirm_download: consent,
                })
              }
            >
              {local.installed
                ? "Use local CPU model"
                : localMode
                  ? "Repair local model"
                  : "Set up semantic memory"}
            </Button>
          )}
          {!local && <p className="muted">Embeddings are not configured.</p>}
          {local && !local.available && (
            <p className="notice">
              The CPU engine is unavailable in this application image.
            </p>
          )}
        </div>
      )}
      {ready && (
        <>
          <div className="memory-semantic-state">
            <div>
              <strong>
                {localMode ? (local?.name ?? current?.model) : current?.model}
              </strong>
              <span className="muted">
                {current?.indexed_count} / {current?.memory_count} memories
                indexed
                {current?.dimension ? ` · ${current.dimension} dimensions` : ""}
              </span>
            </div>
            <Button
              variant="secondary"
              disabled={busy || missing === 0}
              onClick={() => invoke("index")}
            >
              {missing ? "Index remaining memories" : "Index up to date"}
            </Button>
          </div>
          {!!current?.memory_count && (
            <progress
              aria-label="Memory index coverage"
              value={current.indexed_count}
              max={current.memory_count}
            />
          )}
          {!current?.memory_count && (
            <p className="muted">
              Add a memory to start using semantic search.
            </p>
          )}
          <form
            className="memory-semantic-query"
            onSubmit={(e) => {
              e.preventDefault();
              invoke("search", {
                query,
                ...(scope ? { scope } : {}),
                ...(target ? { scope_id: target } : {}),
              });
            }}
          >
            <label>
              <span className="sr-only">Semantic query</span>
              <input
                value={query}
                maxLength={2000}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="What do I prefer when learning something new?"
              />
            </label>
            <Button
              type="submit"
              disabled={
                !query.trim() ||
                operation.isPending ||
                !current?.indexed_count ||
                active(watched.data)
              }
            >
              <Search size={15} aria-hidden="true" /> Search by meaning
            </Button>
          </form>
          <p className="muted memory-semantic-scope">
            Searching {scope || "all"} {scope ? "memories" : "scopes"}
            {target ? ` · ${target.slice(0, 8)}` : ""}. Disabled memories are
            excluded.
          </p>
        </>
      )}
      {running && (
        <div className="memory-semantic-progress" role="status">
          <LoaderCircle size={16} className="spin" aria-hidden="true" />
          <span>
            {download
              ? `Downloading ${download.file}: ${Math.round(download.received_bytes / 1024 ** 2)} / ${Math.ceil(download.expected_bytes / 1024 ** 2)} MiB`
              : progress
                ? `Indexing: ${progress.indexed + progress.skipped_current} / ${progress.total} memories`
                : running.capability === "memory.embed.prepare"
                  ? "Preparing the local model…"
                  : "Working on semantic memory…"}
          </span>
          <StopEmbedding run={running} />
        </div>
      )}
      <ErrorNotice error={setup.error ?? operation.error ?? watched.error} />
      {last &&
        !active(last) &&
        ["failed", "interrupted", "canceled"].includes(last.status) && (
          <p className="notice" role="status">
            {last.status === "canceled"
              ? "Stopped. Existing memories and completed vectors are retained."
              : last.error_message ||
                "Semantic memory needs attention. Inspect the operation and try again."}
          </p>
        )}
      {results && watched.data?.status === "succeeded" && (
        <div
          className="memory-semantic-results"
          aria-label="Semantic search results"
        >
          {!inScope ? (
            <p className="muted">
              The scope changed. Search again to see matching memories.
            </p>
          ) : results.length === 0 ? (
            <p className="muted">
              No indexed memories matched this scope. Add or index memories,
              then search again.
            </p>
          ) : (
            <ul>
              {results.map((hit) => (
                <li key={hit.id}>
                  <Link to={`/memory/${hit.id}`}>
                    <span>{hit.content}</span>
                    <small>
                      {hit.scope} · Similarity {Math.round(hit.score * 100)}%
                    </small>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {last && (
        <p className="memory-semantic-operation">
          <Badge status={last.status} />
          <Link to={`/runs/${last.id}`}>Inspect operation</Link>
        </p>
      )}
      <details className="memory-semantic-advanced">
        <summary>Advanced · existing local endpoint</summary>
        {current?.configured && !localMode && (
          <p className="muted">
            Using {current.model} at {current.endpoint}
          </p>
        )}
        <p className="muted">
          Connect an embedding model you already serve. Save the
          OpenAI-compatible /v1 base URL.
        </p>
        <div className="memory-semantic-endpoint">
          <label>
            Local embeddings base URL
            <input
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="http://host.docker.internal:8080/v1"
            />
          </label>
          <label>
            Model name already served by that endpoint
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="Your embedding model"
            />
          </label>
        </div>
        <div className="row">
          <Button
            disabled={busy || !endpoint || !model}
            onClick={() =>
              operation.mutate({
                path: "setup",
                method: "PUT",
                body: {
                  endpoint,
                  model,
                  expected_revision: current?.revision ?? 0,
                },
              })
            }
          >
            Save local setup
          </Button>
          <Button
            variant="secondary"
            disabled={!current?.configured || busy}
            onClick={() => invoke("health")}
          >
            Check endpoint
          </Button>
          {current?.configured && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() =>
                operation.mutate({
                  path: "setup",
                  method: "PUT",
                  body: {
                    clear: true,
                    expected_revision: current.revision ?? 0,
                  },
                })
              }
            >
              Clear setup
            </Button>
          )}
        </div>
      </details>
    </section>
  );
}

function StopEmbedding({ run }: { run: Run }) {
  const cache = useQueryClient();
  const stop = useMutation({
    mutationFn: () => api<Run>(`/runs/${run.id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["run", run.id] });
      void cache.invalidateQueries({ queryKey: ["memory-embeddings"] });
    },
  });
  return (
    <>
      <Button
        variant="secondary"
        disabled={stop.isPending || run.status === "cancel_requested"}
        onClick={() => stop.mutate()}
      >
        {run.status === "cancel_requested" ? "Stopping…" : "Stop"}
      </Button>
      <ErrorNotice error={stop.error} />
    </>
  );
}
