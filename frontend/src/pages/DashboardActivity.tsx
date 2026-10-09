import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
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

function Section({
  title,
  to,
  children,
  wide,
}: {
  title: string;
  to: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <section className={wide ? "panel dashboard-attention" : "panel"}>
      <div className="panel-heading">
        <h2>{title}</h2>
        <Link className="text-link" to={to}>
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
}: {
  to: string;
  title: string;
  detail: string;
  status?: string;
  thumbnail?: boolean;
  fallback?: ReactNode;
  action?: ReactNode;
}) {
  const id = to.split("/").pop() ?? title;
  return (
    <li className="activity-row">
      <Link to={to}>
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
  const attention =
    interrupted.length +
    notices.filter((row) => !interruptedIds.has(row.run_id)).length +
    active.length;
  return (
    <div className="dashboard-activity">
      <ErrorNotice error={query.error ?? acknowledge.error ?? cancel.error} />
      {query.isPending && <Loading />}
      {data && (
        <div className="dashboard-activity-grid">
          <Section title={`Needs attention · ${attention}`} to="/runs" wide>
            {attention ? (
              <ul className="activity-list">
                {interrupted.map((run) => (
                  <ActivityRow
                    key={`interrupted-${run.id}`}
                    to={`/runs/${run.id}`}
                    title={run.title}
                    detail={`${run.executor_type} · interrupted · not replayed`}
                    status={run.status}
                    action={
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={acknowledge.isPending}
                        onClick={() => acknowledge.mutate(run.id)}
                      >
                        Mark inspected
                      </Button>
                    }
                  />
                ))}
                {notices
                  .filter((notice) => !interruptedIds.has(notice.run_id))
                  .map((notice) => (
                    <ActivityRow
                      key={notice.id}
                      to={`/runs/${notice.run_id}`}
                      title={notice.title}
                      detail={`${notice.kind.replaceAll("_", " ")} · ${time(notice.created_at)}`}
                    />
                  ))}
                {active.map((run) => (
                  <ActivityRow
                    key={run.id}
                    to={`/runs/${run.id}`}
                    title={run.title}
                    detail={
                      run.status === "waiting_for_approval"
                        ? `${run.executor_type} · grant or deny on the Run`
                        : `${run.executor_type} · ${run.execution_target}`
                    }
                    status={run.status}
                    action={
                      CANCELABLE.has(run.status) ? (
                        <Button
                          type="button"
                          variant="secondary"
                          disabled={cancel.isPending}
                          onClick={() => cancel.mutate(run.id)}
                        >
                          Stop
                        </Button>
                      ) : run.status === "cancel_requested" ? (
                        <span className="muted">Stopping…</span>
                      ) : undefined
                    }
                  />
                ))}
              </ul>
            ) : (
              <Empty title="Nothing needs you right now">
                Interrupted work, notices and in-progress Runs will appear here
                with Stop or Mark inspected.
              </Empty>
            )}
          </Section>
          <Section title="Upcoming schedules" to="/agents">
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
          <Section title="Recent conversations" to="/chat">
            {data.conversations.length ? (
              <ul className="activity-list">
                {data.conversations.map((conversation) => (
                  <ActivityRow
                    key={conversation.id}
                    to={`/chat/${conversation.id}`}
                    title={conversation.title}
                    detail={`${conversation.model} · ${time(conversation.updated_at)}`}
                  />
                ))}
              </ul>
            ) : (
              <Empty title="Start a conversation">
                Local model conversations are saved between restarts.
              </Empty>
            )}
          </Section>
          <Section title="Recent artifacts" to="/library">
            {data.artifacts.length ? (
              <ul className="activity-list">
                {data.artifacts.map((artifact) => (
                  <ActivityRow
                    key={artifact.id}
                    to={`/library/${artifact.id}`}
                    title={artifact.name}
                    detail={`${artifact.type} · ${time(artifact.created_at)}`}
                    thumbnail={artifact.has_thumbnail}
                  />
                ))}
              </ul>
            ) : (
              <Empty title="Your outputs live here">
                Images, reports and other Run artifacts share the Library.
              </Empty>
            )}
          </Section>
          <Section title="Runtime observations" to="/system">
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
