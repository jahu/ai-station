import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, type Run } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";

interface RuntimeInstance {
  id: string;
  name: string;
  runtime_key: string;
  ownership: string;
  status: string;
  endpoint: string;
  updated_at: string;
  stale: boolean;
  metadata: {
    source: string;
    pid?: number;
    models?: string[];
    error?: string;
    scan_run_id?: string;
  };
}
export default function RuntimeObservations() {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const registry = useQuery({
    queryKey: ["runtimes", offset],
    queryFn: () =>
      api<{ items: RuntimeInstance[]; total: number; latest_scan: Run | null }>(
        `/runtimes?limit=20&offset=${offset}`,
      ),
    refetchInterval: 15000,
  });
  const refresh = useMutation({
    mutationFn: () =>
      api<Run>("/runtimes/observe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const latest = registry.data?.latest_scan;
  const active =
    latest &&
    !["succeeded", "failed", "interrupted", "canceled"].includes(latest.status);
  return (
    <section className="panel mt">
      <div className="panel-heading">
        <div>
          <h2>External runtimes</h2>
          <p className="muted">
            Saved observations · process presence and endpoint health are
            separate
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={refresh.isPending || Boolean(active)}
          onClick={() => refresh.mutate()}
        >
          Observe runtimes
        </Button>
      </div>
      <div className="runtime-summary">
        <p className="muted">
          Observation does not grant control over a service. Process names are
          hints; only the configured local endpoint is probed. Observations
          older than five minutes are marked stale.
        </p>
        {latest && (
          <Link to={`/runs/${latest.id}`}>
            Latest observation: {latest.status} · {time(latest.created_at)}
          </Link>
        )}
        <ErrorNotice error={registry.error ?? refresh.error} />
      </div>
      {registry.isPending ? (
        <Loading />
      ) : !registry.data?.items.length ? (
        <Empty title="No runtime observations">
          Observe runtimes to inspect existing host processes and your
          configured local model endpoint.
        </Empty>
      ) : (
        <div className="diagnostic-list">
          {registry.data.items.map((runtime) => (
            <div key={runtime.id} className="runtime-item">
              <div>
                <strong>{runtime.name}</strong>
                <p>
                  <span className="tiny-tag">{runtime.ownership}</span>{" "}
                  {runtime.metadata.source === "host_process"
                    ? `Host process · PID ${runtime.metadata.pid}`
                    : runtime.endpoint}
                </p>
                <p>
                  {runtime.metadata.source === "host_process"
                    ? "Process observation does not verify inference readiness."
                    : "Endpoint status checks model discovery, not generation."}
                </p>
                {runtime.metadata.models?.length ? (
                  <p>Advertised models: {runtime.metadata.models.join(", ")}</p>
                ) : null}
                {runtime.metadata.error && <p>{runtime.metadata.error}</p>}
                <small className="muted">
                  Observed {time(runtime.updated_at)}
                  {runtime.stale && " · Stale"} ·{" "}
                  {runtime.metadata.scan_run_id && (
                    <Link to={`/runs/${runtime.metadata.scan_run_id}`}>
                      Source Run
                    </Link>
                  )}
                </small>
              </div>
              <Badge status={runtime.status} />
            </div>
          ))}
        </div>
      )}
      <div className="row runtime-summary">
        <Button
          variant="ghost"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          Previous
        </Button>
        <span className="muted">
          {registry.data?.total ?? 0} recorded instances
        </span>
        <Button
          variant="ghost"
          disabled={offset + 20 >= (registry.data?.total ?? 0)}
          onClick={() => setOffset(offset + 20)}
        >
          Next
        </Button>
      </div>
    </section>
  );
}
