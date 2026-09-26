import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
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
}
function Section({
  title,
  to,
  children,
}: {
  title: string;
  to: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
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
export default function DashboardActivity() {
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<Overview>("/dashboard"),
    refetchInterval: 10000,
  });
  const data = query.data;
  return (
    <div className="dashboard-activity">
      <ErrorNotice error={query.error} />
      {query.isPending && <Loading />}
      {data && (
        <div className="dashboard-activity-grid">
          <Section title={`In progress · ${data.active_run_count}`} to="/runs">
            {data.active_runs.length ? (
              <div className="activity-list">
                {data.active_runs.map((run) => (
                  <Link key={run.id} to={`/runs/${run.id}`}>
                    <div>
                      <strong>{run.title}</strong>
                      <small>
                        {run.executor_type} · {run.execution_target}
                      </small>
                    </div>
                    <Badge status={run.status} />
                  </Link>
                ))}
              </div>
            ) : (
              <Empty title="No active runs">
                Queued and running work will appear here.
              </Empty>
            )}
          </Section>
          <Section title="Upcoming schedules" to="/agents">
            {data.upcoming.length ? (
              <div className="activity-list">
                {data.upcoming.map((agent) => (
                  <Link key={agent.id} to={`/agents/${agent.id}`}>
                    <div>
                      <strong>{agent.name}</strong>
                      <small>
                        {time(agent.next_run_at)} · {agent.trigger}
                        {agent.overdue && " · Due / waiting for scheduler"}
                      </small>
                    </div>
                  </Link>
                ))}
              </div>
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
              <div className="activity-list">
                {data.agents.map((agent) => (
                  <Link key={agent.id} to={`/agents/${agent.id}`}>
                    <div>
                      <strong>{agent.name}</strong>
                      <small>
                        {agent.model} · {agent.trigger}
                      </small>
                    </div>
                    {agent.last_status ? (
                      <Badge status={agent.last_status} />
                    ) : (
                      <span className="muted">Not run yet</span>
                    )}
                  </Link>
                ))}
              </div>
            ) : (
              <Empty title="No enabled agents">
                Create and inspect a draft before activating it.
              </Empty>
            )}
          </Section>
          <Section title="Recent conversations" to="/chat">
            {data.conversations.length ? (
              <div className="activity-list">
                {data.conversations.map((conversation) => (
                  <Link key={conversation.id} to={`/chat/${conversation.id}`}>
                    <div>
                      <strong>{conversation.title}</strong>
                      <small>
                        {conversation.model} · {time(conversation.updated_at)}
                      </small>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <Empty title="Start a conversation">
                Local model conversations are saved between restarts.
              </Empty>
            )}
          </Section>
          <Section title="Recent artifacts" to="/library">
            {data.artifacts.length ? (
              <div className="activity-list">
                {data.artifacts.map((artifact) => (
                  <Link key={artifact.id} to={`/library/${artifact.id}`}>
                    {artifact.has_thumbnail && (
                      <img
                        className="dashboard-thumbnail"
                        src={`/api/artifacts/${artifact.id}/thumbnail`}
                        alt=""
                        loading="lazy"
                      />
                    )}
                    <div>
                      <strong>{artifact.name}</strong>
                      <small>
                        {artifact.type} · {time(artifact.created_at)}
                      </small>
                    </div>
                  </Link>
                ))}
              </div>
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
              <div className="activity-list">
                {data.runtimes.map((runtime) => (
                  <Link key={runtime.id} to="/system">
                    <div>
                      <strong>{runtime.name}</strong>
                      <small>
                        {runtime.ownership} ·{" "}
                        {runtime.source === "host_process"
                          ? "Process"
                          : "Endpoint"}{" "}
                        · {time(runtime.updated_at)}
                        {runtime.stale && " · Stale"}
                      </small>
                    </div>
                    <Badge status={runtime.status} />
                  </Link>
                ))}
              </div>
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
