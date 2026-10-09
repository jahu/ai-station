import ChatProviders from "./ChatProviders";
import Connectors from "./Connectors";
import Maintenance from "./Maintenance";
import OperatorAccess from "./OperatorAccess";
import RuntimeObservations from "./RuntimeObservations";
import { useId, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { useListKeyboard } from "./useListKeyboard";

type Lease = NonNullable<Status["leases"]>[number];
type Worker = Status["workers"][number];

function WorkerCards({ workers }: { workers: Worker[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    workers,
    (worker) => worker.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Worker heartbeats
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a worker while the list is focused. There is no
        inspectable heartbeat Run. Held leases stay a separate list.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {workers.map((worker, i) => (
          <div
            key={worker.id}
            aria-label={`Worker ${worker.id}`}
            {...itemProps(i, worker.id)}
          >
            <div>
              <strong className="mono">{worker.id}</strong>
              <p>Last heartbeat {time(worker.last_heartbeat)}</p>
            </div>
            <Badge status={worker.available ? "available" : "unavailable"} />
          </div>
        ))}
      </div>
    </section>
  );
}

function CheckCards({ checks }: { checks: Diagnostic[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    checks,
    (check) => check.name,
  );
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Integration checks
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a check while the list is focused. There is no
        inspectable diagnostic Run. Refresh stays outside this list.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {checks.map((check, i) => (
          <div
            key={check.name}
            aria-label={`Check ${check.name}`}
            {...itemProps(i, check.name)}
          >
            <div>
              <strong>{check.name}</strong>
              <p>{check.detail}</p>
            </div>
            <Badge status={check.status} />
          </div>
        ))}
      </div>
    </section>
  );
}

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
        ) : diagnostics.data?.checks.length ? (
          <CheckCards checks={diagnostics.data.checks} />
        ) : null}
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
        {status.data?.workers.length ? (
          <WorkerCards workers={status.data.workers} />
        ) : (
          <p className="muted">No worker has registered yet.</p>
        )}
        <LeaseHealth status={status.data} />
      </section>
    </>
  );
}

function LeaseCards({ leases }: { leases: Lease[] }) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    leases,
    (lease) => lease.id,
  );
  const selected = leases[index];
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.id) {
      event.preventDefault();
      navigate(`/runs/${selected.id}`);
    }
  };
  return (
    <section aria-labelledby={headingId}>
      <h4 id={headingId} className="sr-only">
        Worker leases
      </h4>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a lease while the list is focused. Enter inspects its
        Run. This page does not recover, requeue or restore them.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {leases.map((lease, i) => {
          const current = i === index;
          const shortId = lease.id.slice(0, 8);
          return (
            <div key={lease.id} {...itemProps(i, lease.id)}>
              <div>
                <Link
                  className="text-link mono"
                  to={`/runs/${lease.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect ${shortId}`}
                >
                  {shortId}
                </Link>
                <p>
                  {lease.executor_type} · {lease.retry_class}
                  {lease.stale ? " · expired" : ""} · replay{" "}
                  {lease.replay ? "yes" : "no"}
                </p>
              </div>
              <Badge status={lease.stale ? "interrupted" : lease.status} />
            </div>
          );
        })}
      </div>
    </section>
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
        <LeaseCards leases={leases} />
      ) : (
        <p className="muted">No worker currently holds a run lease.</p>
      )}
    </div>
  );
}
