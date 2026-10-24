import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, type KeyboardEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Download } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";

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

type BackupArtifact = {
  id: string;
  type: string;
  filename: string;
  size_bytes: number;
  relative_path: string;
};

type BackupList = {
  items: Array<Run & { restore: string; artifacts?: BackupArtifact[] }>;
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
  sha256?: string;
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

type ComposeContainer = ImageInspect["containers"][number];
type BackupRow = Run & { restore: string; artifacts?: BackupArtifact[] };

function OfflineRecoveryGuide({ copy }: { copy: BackupInspect }) {
  if (
    copy.status !== "succeeded" ||
    copy.integrity_check !== "ok" ||
    !copy.hash_matches ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      copy.run_id,
    ) ||
    !/^[0-9a-f]{64}$/i.test(copy.sha256 ?? "")
  )
    return null;
  return (
    <details className="maintenance-recovery-guide mt">
      <summary>Recover this backup on the workstation</summary>
      <p className="muted">
        Use a terminal in the same AI Station checkout and data configuration.
        This database copy needs the original application data folder, including
        its artifacts and worktrees.
      </p>
      <ol>
        <li>
          Inspect the copy first. This command does not change your database.
          <pre className="whitespace-pre-wrap break-all">
            <code>{`./scripts/restore.sh --backup-run ${copy.run_id}`}</code>
          </pre>
        </li>
        <li>
          Unload AI Station models in Models, finish or stop active tasks, then
          stop the AI Station supervisor with Ctrl+C in its terminal.
        </li>
        <li>
          After reviewing the inspection, apply this exact copy:
          <pre className="whitespace-pre-wrap break-all">
            <code>{`./scripts/restore.sh --backup-run ${copy.run_id} --apply --expected-sha256 ${copy.sha256}`}</code>
          </pre>
        </li>
        <li>
          Start AI Station with <code>./scripts/start.sh</code>. Your current
          password stays in place. Devices sign in again, agents stay paused and
          interrupted tasks wait for inspection. A private recovery receipt
          records the result and retained original files.
        </li>
      </ol>
      <p className="muted">
        If recovery is interrupted, run{" "}
        <code>./scripts/restore.sh --pending</code> before starting again.
        Follow the recovery guide in <code>docs/operations.md</code> to finish
        or abort that operation.
      </p>
    </details>
  );
}

function ContainerCards({ containers }: { containers: ComposeContainer[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    containers,
    (row) => row.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Compose containers
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a container while the list is focused. Rollout remains
        unpublished.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {containers.map((row, i) => (
          <div
            key={row.id}
            aria-label={`Container ${row.service} ${row.id.slice(0, 8)}`}
            {...itemProps(i, row.id)}
          >
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
        ))}
      </div>
    </section>
  );
}

function BackupCards({
  items,
  inspectPending,
  inspectVariables,
  checked,
  onInspect,
}: {
  items: BackupRow[];
  inspectPending: boolean;
  inspectVariables?: string;
  checked: BackupInspect | null;
  onInspect: (runId: string) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (row) => row.id,
  );
  const selected = items[index];
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    // The recovery disclosure owns its native keys, rather than opening a Run.
    if ((event.target as HTMLElement).closest("details")) return;
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
    <section className="mt" aria-labelledby={headingId}>
      <h3 id={headingId}>Recent copies</h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a copy while the list is focused. Enter inspects its
        backup Run. Inspect copy and Download copy stay on the selected row.
        Download is the stored file. It does not replace the live database.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((row, i) => {
          const current = i === index;
          const shortId = row.id.slice(0, 8);
          const recorded = row.metadata?.backup as BackupReport | undefined;
          const recheck = checked?.run_id === row.id ? checked : null;
          const sqlite = row.artifacts?.find(
            (item) => item.filename === "ai-station.sqlite",
          );
          return (
            <div
              className="maintenance-backup-row"
              key={row.id}
              {...itemProps(i, row.id)}
            >
              <div>
                <strong>{row.summary || "SQLite backup"}</strong>
                <p>
                  {row.status}
                  {recorded?.integrity_check
                    ? ` · recorded integrity_check=${recorded.integrity_check}`
                    : ""}
                  {recheck ? ` · re-check ${recheck.integrity_check}` : ""}
                  {" · in-app restore "}
                  {row.restore}
                </p>
                {recheck ? (
                  <p className="muted">
                    {recheck.summary}
                    {recheck.schema_revision
                      ? ` · copy schema ${recheck.schema_revision}`
                      : ""}
                    {recheck.schema_matches_live
                      ? " · matches live schema"
                      : " · schema differs from live"}
                    {` · ${recheck.relative_path}`}
                  </p>
                ) : null}
                {recheck ? <OfflineRecoveryGuide copy={recheck} /> : null}
              </div>
              <div className="row">
                {row.status === "succeeded" ? (
                  <Button
                    type="button"
                    variant="secondary"
                    tabIndex={current ? 0 : -1}
                    disabled={inspectPending}
                    aria-label={`Inspect copy ${shortId}`}
                    onClick={() => onInspect(row.id)}
                  >
                    {inspectPending && inspectVariables === row.id
                      ? "Checking…"
                      : "Inspect copy"}
                  </Button>
                ) : null}
                {row.status === "succeeded" && sqlite ? (
                  <a
                    className="text-link"
                    href={`/api/artifacts/${sqlite.id}/file`}
                    download={sqlite.filename}
                    tabIndex={current ? 0 : -1}
                    aria-label={`Download copy ${shortId}`}
                  >
                    <Download size={14} />
                    Download copy
                  </a>
                ) : null}
                <Link
                  to={`/runs/${row.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect backup Run ${shortId}`}
                >
                  Open backup Run
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function InterruptedCards({
  items,
  acknowledgePending,
  onAcknowledge,
}: {
  items: InterruptedRun[];
  acknowledgePending: boolean;
  onAcknowledge: (runId: string) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (row) => row.id,
  );
  const selected = items[index];
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
    <section className="mt" aria-labelledby={headingId}>
      <h3 id={headingId}>Interrupted Runs</h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a Run while the list is focused. Enter inspects it.
        Mark inspected stays on the selected row. It does not retry the Run or
        restore a backup.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((row, i) => {
          const current = i === index;
          const shortId = row.id.slice(0, 8);
          const name = row.title || row.summary || row.executor_type;
          return (
            <div key={row.id} {...itemProps(i, row.id)}>
              <div>
                <strong>{name}</strong>
                <p>
                  {row.status} · {row.executor_type} · not replayed
                </p>
              </div>
              <div className="row">
                <Link
                  to={`/runs/${row.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect ${name} ${shortId}`}
                >
                  Open Run
                </Link>
                <Button
                  variant="secondary"
                  tabIndex={current ? 0 : -1}
                  disabled={acknowledgePending}
                  aria-label={`Mark inspected ${name} ${shortId}`}
                  onClick={() => onAcknowledge(row.id)}
                >
                  Mark inspected
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

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
            Verified backups · offline recovery · deployment inspection
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
              <strong>Recovery and private access</strong>
              <p>
                In-app restore {ready.restore} · image rollout{" "}
                {ready.image_rollout}
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
          </div>
          {image.data.containers.length ? (
            <ContainerCards containers={image.data.containers} />
          ) : (
            <div className="diagnostic-list">
              <div>
                <div>
                  <strong>No running control-plane containers reported</strong>
                  <p>Rollout remains unpublished.</p>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}
      {(ready?.interrupted_runs.length ?? 0) > 0 ? (
        <InterruptedCards
          items={ready!.interrupted_runs}
          acknowledgePending={acknowledge.isPending}
          onAcknowledge={(runId) => acknowledge.mutate(runId)}
        />
      ) : null}
      {backups.data?.items.length ? (
        <BackupCards
          items={backups.data.items}
          inspectPending={inspect.isPending}
          inspectVariables={inspect.variables}
          checked={inspect.data ?? null}
          onInspect={(runId) => inspect.mutate(runId)}
        />
      ) : null}
    </section>
  );
}
