import { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Ban, Radio } from "lucide-react";
import { api, type Run, type RunEvent, type Artifact, useRuns } from "../api";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { terminal, time } from "../lib/utils";
import { ArtifactCards } from "./Library";

export function Runs() {
  const [status, setStatus] = useState("");
  const query = useRuns(status);
  return (
    <>
      <PageTitle
        eyebrow="EXECUTION / HISTORY"
        title="Every run, accounted for."
      >
        Follow work from the queue to its final result.
      </PageTitle>
      <div className="toolbar">
        <label>
          Filter by status{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {[
              "queued",
              "claimed",
              "preparing",
              "running",
              "waiting_for_approval",
              "succeeded",
              "failed",
              "cancel_requested",
              "canceled",
              "interrupted",
            ].map((s) => (
              <option key={s} value={s}>
                {s.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">Latest 100 runs</span>
      </div>
      <ErrorNotice error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        <section className="panel">
          {query.data?.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Capability / Run</th>
                    <th>Status</th>
                    <th>Executor</th>
                    <th>Target</th>
                    <th>Created</th>
                    <th>
                      <span className="sr-only">Inspect</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link to={`/runs/${run.id}`}>
                          <strong>{run.capability}</strong>
                          <small className="mono">{run.id.slice(0, 8)}</small>
                        </Link>
                      </td>
                      <td>
                        <Badge status={run.status} />
                      </td>
                      <td>{run.executor_type}</td>
                      <td>
                        <span className="chip">{run.execution_target}</span>
                      </td>
                      <td className="muted">{time(run.created_at)}</td>
                      <td>
                        <Link
                          to={`/runs/${run.id}`}
                          aria-label={`Inspect run ${run.id}`}
                        >
                          <ArrowUpRight size={16} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No runs in this view">
              Tasks appear here when you submit them. Change the filter to see
              other states.
            </Empty>
          )}
        </section>
      )}
    </>
  );
}

export function RunDetail() {
  const navigate = useNavigate();
  const { id } = useParams();
  const cache = useQueryClient();
  const run = useQuery({
    queryKey: ["run", id],
    queryFn: () => api<Run>(`/runs/${id}`),
    refetchInterval: 5000,
  });
  const events = useQuery({
    queryKey: ["events", id],
    queryFn: () => api<RunEvent[]>(`/runs/${id}/events`),
  });
  const cancel = useMutation({
    mutationFn: () => api(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["run", id] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const artifacts = useQuery({
    queryKey: ["run-artifacts", id],
    queryFn: () => api<Artifact[]>(`/artifacts?run_id=${id}`),
    refetchInterval: 5000,
  });
  const retry = useMutation({
    mutationFn: () => api<Run>(`/images/runs/${id}/retry`, { method: "POST" }),
    onSuccess: (next) => navigate(`/runs/${next.id}`),
  });
  const isTerminal = run.data ? terminal.has(run.data.status) : false;
  useEffect(() => {
    if (!id) return;
    const source = new EventSource(`/api/runs/${id}/stream`);
    source.onmessage = () => {
      void cache.invalidateQueries({ queryKey: ["events", id] });
      void cache.invalidateQueries({ queryKey: ["run", id] });
    };
    source.addEventListener("end", () => source.close());
    return () => source.close();
  }, [id, cache]);
  return (
    <>
      <Link className="back-link" to="/runs">
        <ArrowLeft size={15} />
        All runs
      </Link>
      <PageTitle
        eyebrow="EXECUTION / INSPECTOR"
        title={run.data?.capability ?? "Run details"}
        action={
          run.data &&
          !isTerminal && (
            <Button
              variant="secondary"
              disabled={
                cancel.isPending || run.data.status === "cancel_requested"
              }
              onClick={() => cancel.mutate()}
            >
              <Ban size={15} />{" "}
              {run.data.status === "cancel_requested"
                ? "Cancellation requested"
                : "Cancel run"}
            </Button>
          )
        }
      >
        <span className="mono">{id}</span>
      </PageTitle>
      <ErrorNotice
        error={
          run.error ??
          events.error ??
          cancel.error ??
          retry.error ??
          artifacts.error
        }
      />
      {run.isPending ? (
        <Loading />
      ) : (
        run.data && (
          <>
            <div className="run-meta panel">
              <Badge status={run.data.status} />
              <span>
                Executor <b>{run.data.executor_type}</b>
              </span>
              <span>
                Target <b>{run.data.execution_target}</b>
              </span>
              <span>
                GPU <b>{run.data.actual_gpu ?? "none"}</b>
              </span>
              <span>
                Started <b>{time(run.data.started_at)}</b>
              </span>
            </div>
            {run.data.error_message && (
              <div className="notice" role="alert">
                {run.data.error_message}
              </div>
            )}
            {run.data.project_id && (
              <p className="mt">
                <Link
                  className="back-link"
                  to={`/projects/${run.data.project_id}`}
                >
                  Open project and worktrees →
                </Link>
              </p>
            )}
            {run.data.parent_run_id && (
              <p>
                <Link to={`/runs/${run.data.parent_run_id}`}>
                  View original run →
                </Link>
              </p>
            )}
            {run.data.executor_type === "photo_pipe" &&
              ["failed", "canceled", "interrupted"].includes(
                run.data.status,
              ) && (
                <div className="panel content-panel">
                  <p>
                    A retry creates a new run with the same parameters and
                    source images. Inspect logs and any partial output before
                    repeating an interrupted run.
                  </p>
                  <Button
                    variant="secondary"
                    disabled={retry.isPending}
                    onClick={() => retry.mutate()}
                  >
                    Retry as a new run
                  </Button>
                </div>
              )}
            {artifacts.data && artifacts.data.length > 0 && (
              <ArtifactCards artifacts={artifacts.data} />
            )}
            {run.data.summary && (
              <section className="panel content-panel">
                <h2>Result</h2>
                <p>{run.data.summary}</p>
              </section>
            )}
            <div className="inspector-grid">
              <section className="panel">
                <div className="panel-heading">
                  <h2>Execution timeline</h2>
                  <span className="muted row">
                    <Radio size={14} />
                    {isTerminal ? "Recorded events" : "Live events"}
                  </span>
                </div>
                <div className="timeline">
                  {events.data?.map((event) => (
                    <article key={event.id}>
                      <span className="timeline-node" />
                      <div className="row spread">
                        <strong>{event.event_type}</strong>
                        <time>
                          {new Date(event.created_at).toLocaleTimeString()}
                        </time>
                      </div>
                      <pre>
                        {typeof event.payload.text === "string"
                          ? event.payload.text
                          : JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </article>
                  ))}
                </div>
              </section>
              <aside className="panel content-panel">
                <h2>Execution context</h2>
                <label>Parameters</label>
                <pre>{JSON.stringify(run.data.parameters, null, 2)}</pre>
                <label>Effective permissions</label>
                <div className="chips">
                  {run.data.effective_permissions.length ? (
                    run.data.effective_permissions.map((p) => (
                      <span className="chip" key={p}>
                        {p}
                      </span>
                    ))
                  ) : (
                    <span className="muted">No additional permissions</span>
                  )}
                </div>
                <label>Worker</label>
                <p className="mono muted">
                  {run.data.worker_id ?? "Not claimed"}
                </p>
                <label>Created</label>
                <p>{time(run.data.created_at)}</p>
                <label>Finished</label>
                <p>{time(run.data.finished_at)}</p>
              </aside>
            </div>
          </>
        )
      )}
    </>
  );
}
