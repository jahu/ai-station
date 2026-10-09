import {
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";

interface AgentSummary {
  id: string;
  name: string;
  model: string;
  trigger: string;
  next_run_at: string | null;
  last_status: string;
  overdue?: boolean;
}
interface Overview {
  active_run_count: number;
  enabled_agent_count: number;
  active_runs: {
    id: string;
    title: string;
    status: string;
    executor_type: string;
    execution_target: string;
  }[];
  upcoming: AgentSummary[];
  agents: AgentSummary[];
  conversations: {
    id: string;
    title: string;
    model: string;
    updated_at: string;
  }[];
  artifacts: {
    id: string;
    type: string;
    name: string;
    created_at: string;
    has_thumbnail: boolean;
  }[];
  runtimes: {
    id: string;
    name: string;
    ownership: string;
    status: string;
    source: string;
    updated_at: string;
    stale: boolean;
  }[];
  unread_notice_count?: number;
  notices?: {
    id: string;
    agent_id: string;
    run_id: string;
    kind: string;
    title: string;
    created_at: string;
  }[];
  interrupted_runs?: {
    id: string;
    title: string;
    status: string;
    executor_type: string;
    replay?: boolean;
  }[];
}

const CANCELABLE = new Set([
  "queued",
  "claimed",
  "preparing",
  "running",
  "waiting_for_approval",
]);

type AttentionItem = {
  key: string;
  to: string;
  title: string;
  detail: string;
  status?: string;
  action?: "acknowledge" | "stop" | "stopping";
  runId?: string;
};

function Section({
  title,
  to,
  viewAll,
  children,
  wide,
}: {
  title: string;
  to: string;
  viewAll: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const headingId = useId();
  return (
    <section
      className={wide ? "panel dashboard-attention" : "panel"}
      aria-labelledby={headingId}
    >
      <div className="panel-heading">
        <h2 id={headingId}>{title}</h2>
        <Link className="text-link" to={to} aria-label={viewAll}>
          View all
        </Link>
      </div>
      {children}
    </section>
  );
}

function ActivityRow({
  to,
  title,
  detail,
  status,
  thumbnail,
  fallback,
  action,
  inspectLabel,
  inspectTabIndex,
  attentionIndex,
  current,
  onInspectFocus,
}: {
  to: string;
  title: string;
  detail: string;
  status?: string;
  thumbnail?: boolean;
  fallback?: ReactNode;
  action?: ReactNode;
  inspectLabel: string;
  inspectTabIndex?: number;
  attentionIndex?: number;
  current?: boolean;
  onInspectFocus?: () => void;
}) {
  const id = to.split("/").pop() ?? title;
  return (
    <li className="activity-row" aria-current={current ? "true" : undefined}>
      <Link
        to={to}
        aria-label={inspectLabel}
        tabIndex={inspectTabIndex}
        data-attention-index={attentionIndex}
        onFocus={onInspectFocus}
      >
        {thumbnail ? (
          <img
            className="dashboard-thumbnail"
            src={`/api/artifacts/${id}/thumbnail`}
            alt=""
            loading="lazy"
          />
        ) : null}
        <div>
          <strong>{title} </strong>
          <small>{detail}</small>
        </div>
        {status ? <Badge status={status} /> : fallback}
      </Link>
      {action ? <div className="activity-actions">{action}</div> : null}
    </li>
  );
}

function attentionAction(
  item: AttentionItem,
  current: boolean,
  handlers: {
    acknowledgePending: boolean;
    cancelPending: boolean;
    onAcknowledge: (runId: string) => void;
    onStop: (runId: string) => void;
    onSelect: () => void;
  },
) {
  const runId = item.runId;
  if (item.action === "acknowledge" && runId) {
    return (
      <Button
        type="button"
        variant="secondary"
        tabIndex={current ? 0 : -1}
        disabled={handlers.acknowledgePending}
        aria-label={`Mark inspected ${item.title}`}
        onFocus={handlers.onSelect}
        onClick={() => handlers.onAcknowledge(runId)}
      >
        Mark inspected
      </Button>
    );
  }
  if (item.action === "stop" && runId) {
    return (
      <Button
        type="button"
        variant="secondary"
        tabIndex={current ? 0 : -1}
        disabled={handlers.cancelPending}
        aria-label={`Stop ${item.title}`}
        onFocus={handlers.onSelect}
        onClick={() => handlers.onStop(runId)}
      >
        Stop
      </Button>
    );
  }
  if (item.action === "stopping") {
    return <span className="muted">Stopping…</span>;
  }
  return undefined;
}

function AttentionList({
  items,
  acknowledgePending,
  cancelPending,
  onAcknowledge,
  onStop,
}: {
  items: AttentionItem[];
  acknowledgePending: boolean;
  cancelPending: boolean;
  onAcknowledge: (runId: string) => void;
  onStop: (runId: string) => void;
}) {
  const labelId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const navigate = useNavigate();
  const [selectedKey, setSelectedKey] = useState(items[0]?.key ?? "");
  const found = items.findIndex((item) => item.key === selectedKey);
  const index = found >= 0 ? found : 0;
  const selected = items[index];
  const focusItem = (next: number) => {
    const clamped = Math.max(0, Math.min(items.length - 1, next));
    const item = items[clamped];
    if (!item) return;
    setSelectedKey(item.key);
    const link = listRef.current?.querySelector<HTMLElement>(
      `[data-attention-index="${clamped}"]`,
    );
    link?.focus();
    link?.scrollIntoView?.({ block: "nearest" });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      focusItem(index + 1);
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      focusItem(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusItem(items.length - 1);
    } else if (event.key === "Enter" && event.target === event.currentTarget) {
      event.preventDefault();
      if (selected) navigate(selected.to);
    }
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an item while the list is focused. Enter inspects it.
        Stop and Mark inspected stay on the selected row.
      </p>
      <ul
        ref={listRef}
        className="activity-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <ActivityRow
              key={item.key}
              to={item.to}
              title={item.title}
              detail={item.detail}
              status={item.status}
              inspectLabel={`Inspect ${item.title}`}
              inspectTabIndex={current ? 0 : -1}
              attentionIndex={i}
              current={current}
              onInspectFocus={() => setSelectedKey(item.key)}
              action={attentionAction(item, current, {
                acknowledgePending,
                cancelPending,
                onAcknowledge,
                onStop,
                onSelect: () => setSelectedKey(item.key),
              })}
            />
          );
        })}
      </ul>
    </>
  );
}

export default function DashboardActivity() {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<Overview>("/dashboard"),
    refetchInterval: 10000,
  });
  const acknowledge = useMutation({
    mutationFn: (runId: string) =>
      api(`/maintenance/interrupted/${runId}/acknowledge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
      void cache.invalidateQueries({ queryKey: ["maintenance"] });
    },
  });
  const cancel = useMutation({
    mutationFn: (runId: string) =>
      api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      void cache.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const data = query.data;
  const interrupted = data?.interrupted_runs ?? [];
  const notices = data?.notices ?? [];
  const active = data?.active_runs ?? [];
  const interruptedIds = new Set(interrupted.map((row) => row.id));
  const attentionItems: AttentionItem[] = [
    ...interrupted.map((run) => ({
      key: `interrupted-${run.id}`,
      to: `/runs/${run.id}`,
      title: run.title,
      detail: `${run.executor_type} · interrupted · not replayed`,
      status: run.status,
      action: "acknowledge" as const,
      runId: run.id,
    })),
    ...notices
      .filter((notice) => !interruptedIds.has(notice.run_id))
      .map((notice) => ({
        key: notice.id,
        to: `/runs/${notice.run_id}`,
        title: notice.title,
        detail: `${notice.kind.replaceAll("_", " ")} · ${time(notice.created_at)}`,
      })),
    ...active.map((run) => ({
      key: run.id,
      to: `/runs/${run.id}`,
      title: run.title,
      detail:
        run.status === "waiting_for_approval"
          ? `${run.executor_type} · grant or deny on the Run`
          : `${run.executor_type} · ${run.execution_target}`,
      status: run.status,
      action: CANCELABLE.has(run.status)
        ? ("stop" as const)
        : run.status === "cancel_requested"
          ? ("stopping" as const)
          : undefined,
      runId: run.id,
    })),
  ];
  const attention = attentionItems.length;
  return (
    <div className="dashboard-activity">
      <ErrorNotice error={query.error ?? acknowledge.error ?? cancel.error} />
      {query.isPending && <Loading />}
      {data && (
        <div className="dashboard-activity-grid">
          <Section
            title={`Needs attention · ${attention}`}
            to="/runs"
            viewAll="View all runs"
            wide
          >
            {attention ? (
              <AttentionList
                items={attentionItems}
                acknowledgePending={acknowledge.isPending}
                cancelPending={cancel.isPending}
                onAcknowledge={(runId) => acknowledge.mutate(runId)}
                onStop={(runId) => cancel.mutate(runId)}
              />
            ) : (
              <Empty title="Nothing needs you right now">
                Interrupted work, notices and in-progress Runs will appear here
                with Stop or Mark inspected.
              </Empty>
            )}
          </Section>
          <Section
            title="Upcoming schedules"
            to="/agents"
            viewAll="View all scheduled agents"
          >
            {data.upcoming.length ? (
              <ul className="activity-list">
                {data.upcoming.map((agent) => (
                  <ActivityRow
                    key={agent.id}
                    to={`/agents/${agent.id}`}
                    title={agent.name}
                    detail={`${time(agent.next_run_at)} · ${agent.trigger}${
                      agent.overdue ? " · Due / waiting for scheduler" : ""
                    }`}
                    inspectLabel={`Inspect ${agent.name}`}
                  />
                ))}
              </ul>
            ) : (
              <Empty title="Nothing scheduled">
                Enable an agent with a schedule to see its next due time.
              </Empty>
            )}
          </Section>
          <Section
            title={`Enabled agents · ${data.enabled_agent_count}`}
            to="/agents"
            viewAll="View all agents"
          >
            {data.agents.length ? (
              <ul className="activity-list">
                {data.agents.map((agent) => (
                  <ActivityRow
                    key={agent.id}
                    to={`/agents/${agent.id}`}
                    title={agent.name}
                    detail={`${agent.model} · ${agent.trigger}`}
                    status={agent.last_status || undefined}
                    inspectLabel={`Inspect ${agent.name}`}
                    fallback={
                      agent.last_status ? undefined : (
                        <span className="muted">Not run yet</span>
                      )
                    }
                  />
                ))}
              </ul>
            ) : (
              <Empty title="No enabled agents">
                Create and inspect a draft before activating it.
              </Empty>
            )}
          </Section>
          <Section
            title="Recent conversations"
            to="/chat"
            viewAll="View all conversations"
          >
            {data.conversations.length ? (
              <ul className="activity-list">
                {data.conversations.map((conversation) => (
                  <ActivityRow
                    key={conversation.id}
                    to={`/chat/${conversation.id}`}
                    title={conversation.title}
                    detail={`${conversation.model} · ${time(conversation.updated_at)}`}
                    inspectLabel={`Inspect ${conversation.title}`}
                  />
                ))}
              </ul>
            ) : (
              <Empty title="Start a conversation">
                Local model conversations are saved between restarts.
              </Empty>
            )}
          </Section>
          <Section
            title="Recent artifacts"
            to="/library"
            viewAll="View all library artifacts"
          >
            {data.artifacts.length ? (
              <ul className="activity-list">
                {data.artifacts.map((artifact) => (
                  <ActivityRow
                    key={artifact.id}
                    to={`/library/${artifact.id}`}
                    title={artifact.name}
                    detail={`${artifact.type} · ${time(artifact.created_at)}`}
                    thumbnail={artifact.has_thumbnail}
                    inspectLabel={`Inspect ${artifact.name}`}
                  />
                ))}
              </ul>
            ) : (
              <Empty title="Your outputs live here">
                Images, reports and other Run artifacts share the Library.
              </Empty>
            )}
          </Section>
          <Section
            title="Runtime observations"
            to="/system"
            viewAll="View all system diagnostics"
          >
            <p className="dashboard-note">
              Saved observations. Process presence does not verify inference
              readiness.
            </p>
            {data.runtimes.length ? (
              <ul className="activity-list">
                {data.runtimes.map((runtime) => (
                  <ActivityRow
                    key={runtime.id}
                    to="/system"
                    title={runtime.name}
                    detail={`${runtime.ownership} · ${
                      runtime.source === "host_process" ? "Process" : "Endpoint"
                    } · ${time(runtime.updated_at)}${
                      runtime.stale ? " · Stale" : ""
                    }`}
                    status={runtime.status}
                    inspectLabel={`Inspect ${runtime.name}`}
                  />
                ))}
              </ul>
            ) : (
              <Empty title="No observations yet">
                Open System to inspect the existing runtimes.
              </Empty>
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
