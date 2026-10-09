import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

type InterruptedRun = Run & {
  title?: string;
  replay?: boolean;
  restore?: string;
};

type Readiness = {
  schema_revision: string | null;
  schema_head: string | null;
  schema_current_matches_head: boolean;
  database: string;
  journal_mode: string;
  active_runs: number;
  upgrade_blocked_by_active_runs: boolean;
  data_survives_compose_down: boolean;
  compose_down_removes_bind_data: boolean;
  application_data: string;
  restore: string;
  image_rollout: string;
  lan_bind_allowed: boolean;
  last_backup: Run | null;
  interrupted_runs: InterruptedRun[];
  summary: string;
};

type BackupList = {
  items: Array<Run & { restore: string }>;
  restore: string;
};

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function Maintenance() {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const status = useQuery({
    queryKey: ["maintenance"],
    queryFn: () => api<Readiness>("/maintenance"),
  });
  const backups = useQuery({
    queryKey: ["maintenance-backups"],
    queryFn: () => api<BackupList>("/maintenance/backups"),
  });
  const backup = useMutation({
    mutationFn: () => api<Run>("/maintenance/backups", json("POST", {})),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["maintenance"] });
      void cache.invalidateQueries({ queryKey: ["maintenance-backups"] });
      navigate(`/runs/${run.id}`);
    },
  });
  const acknowledge = useMutation({
    mutationFn: (runId: string) =>
      api<Run>(
        `/maintenance/interrupted/${runId}/acknowledge`,
        json("POST", {}),
      ),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["maintenance"] });
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const ready = status.data;
  const activeBackup = backups.data?.items.some(
    (row) =>
      !["succeeded", "failed", "interrupted", "canceled"].includes(row.status),
  );
  return (
    <section className="panel mt">
      <div className="panel-heading">
        <div>
          <h2>Backup and upgrade readiness</h2>
          <p className="muted">
            Inspect-only · restore and image rollout stay unpublished
          </p>
        </div>
        <Badge
          status={
            ready?.schema_current_matches_head ? "available" : "unavailable"
          }
        />
      </div>
      <p className="muted">{ready?.summary}</p>
      <ErrorNotice
        error={
          status.error ?? backups.error ?? backup.error ?? acknowledge.error
        }
      />
      {ready ? (
        <div className="diagnostic-list">
          <div>
            <div>
              <strong>Schema</strong>
              <p>
                {ready.schema_revision ?? "unknown"} / head{" "}
                {ready.schema_head ?? "unknown"}
                {ready.schema_current_matches_head ? " · matches code" : ""}
              </p>
            </div>
          </div>
          <div>
            <div>
              <strong>Database</strong>
              <p>
                <code>{ready.database}</code> · {ready.journal_mode}
                {" · "}
                {ready.active_runs} active Runs
                {ready.upgrade_blocked_by_active_runs
                  ? " · wait before upgrading"
                  : ""}
              </p>
            </div>
          </div>
          <div>
            <div>
              <strong>Compose down</strong>
              <p>
                Bind-mounted application data survives container shutdown.
                {ready.compose_down_removes_bind_data
                  ? " Unexpected: volume wipe would delete data."
                  : " The launcher never passes --volumes."}
              </p>
            </div>
          </div>
          <div>
            <div>
              <strong>Not enabled</strong>
              <p>
                Restore {ready.restore} · image rollout {ready.image_rollout}
                {" · "}
                LAN bind {ready.lan_bind_allowed ? "allowed" : "refused"}
              </p>
            </div>
          </div>
        </div>
      ) : null}
      {ready?.last_backup ? (
        <p>
          <Link to={`/runs/${ready.last_backup.id}`}>
            Latest backup Run: {ready.last_backup.status}
          </Link>
        </p>
      ) : null}
      <div className="row mt">
        <Button
          disabled={backup.isPending || Boolean(activeBackup)}
          onClick={() => backup.mutate()}
        >
          {backup.isPending ? "Queueing…" : "Back up SQLite"}
        </Button>
      </div>
      {(ready?.interrupted_runs.length ?? 0) > 0 ? (
        <div className="mt">
          <h3>Interrupted Runs</h3>
          <p className="muted">
            Marking inspected does not retry the Run or restore a backup.
          </p>
          <div className="diagnostic-list">
            {ready!.interrupted_runs.map((row) => (
              <div key={row.id}>
                <div>
                  <strong>
                    {row.title || row.summary || row.executor_type}
                  </strong>
                  <p>
                    {row.status} · {row.executor_type} · not replayed
                  </p>
                </div>
                <div className="row">
                  <Link to={`/runs/${row.id}`}>Open Run</Link>
                  <Button
                    variant="secondary"
                    disabled={acknowledge.isPending}
                    onClick={() => acknowledge.mutate(row.id)}
                  >
                    Mark inspected
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {backups.data?.items.length ? (
        <div className="diagnostic-list mt">
          {backups.data.items.map((row) => (
            <div key={row.id}>
              <div>
                <strong>{row.summary || "SQLite backup"}</strong>
                <p>
                  {row.status} · restore {row.restore}
                </p>
              </div>
              <Link to={`/runs/${row.id}`}>Open backup Run</Link>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
