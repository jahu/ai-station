import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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

type BackupReport = {
  integrity_check?: string;
  schema_revision?: string | null;
};

type BackupList = {
  items: Array<Run & { restore: string }>;
  restore: string;
};

type BackupInspect = {
  run_id: string;
  status: string;
  integrity_check: string;
  hash_matches: boolean;
  size_bytes: number;
  schema_revision: string | null;
  live_schema_revision: string | null;
  schema_matches_live: boolean;
  restore: string;
  image_rollout: string;
  replay: boolean;
  summary: string;
  relative_path: string;
};

type ImageInspect = {
  docker: string;
  runner?: string;
  tag: {
    name: string;
    present: boolean;
    id: string | null;
    created: string | null;
  };
  containers: {
    id: string;
    name: string;
    service: string;
    project: string;
    status: string;
    image: string;
    image_id: string | null;
    matches_tag: boolean;
    self?: boolean;
  }[];
  matches_running: boolean;
  self_container_id?: string | null;
  restore: string;
  image_rollout: string;
  summary: string;
};

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function Maintenance() {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  useEffect(() => {
    if (params.get("focus") === "maintenance") {
      document.getElementById("maintenance")?.focus();
    }
  }, [params]);
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
  const inspect = useMutation({
    mutationFn: (runId: string) =>
      api<BackupInspect>(`/maintenance/backups/${runId}`),
  });
  const image = useMutation({
    mutationFn: () => api<ImageInspect>("/maintenance/image"),
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
    <section className="panel mt" id="maintenance" tabIndex={-1}>
      <div className="panel-heading">
        <div>
          <h2>Backup and upgrade readiness</h2>
          <p className="muted">
            Inspect a verified copy · restore and image rollout stay unpublished
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
          status.error ??
          backups.error ??
          backup.error ??
          inspect.error ??
          image.error ??
          acknowledge.error
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
        <Button
          type="button"
          variant="secondary"
          disabled={image.isPending}
          onClick={() => image.mutate()}
        >
          {image.isPending ? "Inspecting…" : "Inspect running image"}
        </Button>
      </div>
      {image.data ? (
        <div className="mt">
          <h3>Compose image</h3>
          <p className="muted">{image.data.summary}</p>
          <div className="diagnostic-list">
            <div>
              <div>
                <strong>{image.data.tag.name}</strong>
                <p>
                  {image.data.tag.present
                    ? `present · ${image.data.tag.id ?? "id unknown"}`
                    : "tag not present on this host"}
                  {` · rollout ${image.data.image_rollout}`}
                </p>
              </div>
            </div>
            {image.data.containers.length ? (
              image.data.containers.map((row) => (
                <div key={row.id}>
                  <div>
                    <strong>
                      {row.service}
                      {row.self ? " · this API" : ""}
                    </strong>
                    <p>
                      {row.project} · {row.status}
                      {row.matches_tag
                        ? " · matches ai-station:local"
                        : " · differs from current tag"}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <div>
                <div>
                  <strong>No running control-plane containers reported</strong>
                  <p>Rollout remains unpublished.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}
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
          {backups.data.items.map((row) => {
            const recorded = row.metadata?.backup as BackupReport | undefined;
            const checked =
              inspect.data?.run_id === row.id ? inspect.data : null;
            return (
              <div key={row.id}>
                <div>
                  <strong>{row.summary || "SQLite backup"}</strong>
                  <p>
                    {row.status}
                    {recorded?.integrity_check
                      ? ` · recorded integrity_check=${recorded.integrity_check}`
                      : ""}
                    {checked
                      ? ` · re-check ${checked.integrity_check}`
                      : ""}
                    {" · restore "}
                    {row.restore}
                  </p>
                  {checked ? (
                    <p className="muted">
                      {checked.summary}
                      {checked.schema_revision
                        ? ` · copy schema ${checked.schema_revision}`
                        : ""}
                      {checked.schema_matches_live
                        ? " · matches live schema"
                        : " · schema differs from live"}
                      {` · ${checked.relative_path}`}
                    </p>
                  ) : null}
                </div>
                <div className="row">
                  {row.status === "succeeded" ? (
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={inspect.isPending}
                      onClick={() => inspect.mutate(row.id)}
                    >
                      {inspect.isPending && inspect.variables === row.id
                        ? "Checking…"
                        : "Inspect copy"}
                    </Button>
                  ) : null}
                  <Link to={`/runs/${row.id}`}>Open backup Run</Link>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
