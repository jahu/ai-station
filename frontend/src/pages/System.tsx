import ChatProviders from "./ChatProviders";
import Connectors from "./Connectors";
import Maintenance from "./Maintenance";
import OperatorAccess from "./OperatorAccess";
import RuntimeObservations from "./RuntimeObservations";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, ShieldCheck } from "lucide-react";
import {
  api,
  type Diagnostic,
  type Status,
  useHardware,
  useStatus,
} from "../api";
import { Badge, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { number, time } from "../lib/utils";

export default function System() {
  const hardware = useHardware();
  const status = useStatus();
  const diagnostics = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => api<{ checks: Diagnostic[] }>("/system/diagnostics"),
    staleTime: 60000,
  });
  return (
    <>
      <PageTitle
        eyebrow="WORKSTATION / DIAGNOSTICS"
        title="Know what’s available."
        action={
          <Button
            variant="secondary"
            disabled={diagnostics.isFetching}
            onClick={() => void diagnostics.refetch()}
          >
            <RefreshCw size={15} />
            Refresh checks
          </Button>
        }
      >
        Read-only checks of your host, execution tools, and configured
        resources.
      </PageTitle>
      <div className="info-banner">
        <ShieldCheck size={20} />
        <div>
          <strong>Your existing services stay yours.</strong>
          <p>
            Discovery does not install, restart, reconfigure, or take ownership
            of external runtimes.
          </p>
        </div>
      </div>
      <ErrorNotice
        error={hardware.error ?? diagnostics.error ?? status.error}
      />
      <div className="metrics-grid">
        <section className="panel metric">
          <span>CPU temperature</span>
          <strong>{number(hardware.data?.cpu.temperature_c, "°C")}</strong>
          <small>Unavailable when no supported sensor is present</small>
        </section>
        <section className="panel metric">
          <span>Swap in use</span>
          <strong>{number(hardware.data?.memory.swap_used_mib, " MiB")}</strong>
        </section>
        <section className="panel metric">
          <span>Load average · 1 minute</span>
          <strong>{hardware.data?.load["1"]?.toFixed(2) ?? "—"}</strong>
        </section>
        <section className="panel metric">
          <span>Scheduler</span>
          <Badge
            status={
              status.data?.scheduler.available ? "available" : "unavailable"
            }
          />
          <small>{time(status.data?.scheduler.last_heartbeat ?? null)}</small>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>Integration checks</h2>
          <span className="muted">Actual host state</span>
        </div>
        {diagnostics.isPending ? (
          <Loading />
        ) : (
          <div className="diagnostic-list">
            {diagnostics.data?.checks.map((check) => (
              <div key={check.name}>
                <div>
                  <strong>{check.name}</strong>
                  <p>{check.detail}</p>
                </div>
                <Badge status={check.status} />
              </div>
            ))}
          </div>
        )}
      </section>
      <OperatorAccess />
      <Maintenance />
      <ChatProviders />
      <Connectors />
      <RuntimeObservations />
      <section className="panel mt">
        <div className="panel-heading">
          <h2>Workers</h2>
          <span className="muted">Durable execution leases</span>
        </div>
        <div className="diagnostic-list">
          {status.data?.workers.length ? (
            status.data.workers.map((w) => (
              <div key={w.id}>
                <div>
                  <strong className="mono">{w.id}</strong>
                  <p>Last heartbeat {time(w.last_heartbeat)}</p>
                </div>
                <Badge status={w.available ? "available" : "unavailable"} />
              </div>
            ))
          ) : (
            <p className="muted">No worker has registered yet.</p>
          )}
        </div>
        <LeaseHealth status={status.data} />
      </section>
    </>
  );
}

function LeaseHealth({ status }: { status?: Status }) {
  const leases = status?.leases ?? [];
  const stale = status?.stale_lease_count ?? 0;
  const workerAvailable = status?.workers.some((row) => row.available);
  return (
    <div className="mt">
      <div className="panel-heading">
        <h3>Held leases</h3>
        <span className="muted">
          {status?.held_lease_count ?? 0} held · {stale} expired ·{" "}
          {status?.lease_seconds ?? "—"}s length
        </span>
      </div>
      <p className="muted">
        Inspect-only. Expired leases wait for the next worker tick. This page
        does not recover, requeue or restore them.
      </p>
      {stale > 0 && (
        <p className="notice">
          {stale} expired lease{stale === 1 ? "" : "s"} waiting for a worker
          tick.
          {!workerAvailable
            ? " No available worker is registered, so recovery is paused."
            : ""}
        </p>
      )}
      {leases.length ? (
        <div className="diagnostic-list">
          {leases.map((lease) => (
            <div key={lease.id}>
              <div>
                <Link className="text-link mono" to={`/runs/${lease.id}`}>
                  {lease.id.slice(0, 8)}
                </Link>
                <p>
                  {lease.executor_type} · {lease.retry_class}
                  {lease.stale ? " · expired" : ""} · replay{" "}
                  {lease.replay ? "yes" : "no"}
                </p>
              </div>
              <Badge status={lease.stale ? "interrupted" : lease.status} />
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No worker currently holds a run lease.</p>
      )}
    </div>
  );
}
