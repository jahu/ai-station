import { useId, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorNotice, Loading } from "../components/common";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

interface LinkedAgent {
  id: string;
  name: string;
  goal: string;
  model: string;
  enabled: boolean;
  last_status: string;
  next_run_at: string | null;
}

function AgentCards({
  agents,
  projectId,
}: {
  agents: LinkedAgent[];
  projectId: string;
}) {
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    agents,
    (agent) => agent.id,
  );
  const selected = agents[index];
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.id) {
      event.preventDefault();
      navigate(`/agents/${selected.id}`);
    }
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a linked agent while the list is focused. Enter
        inspects it. View tagged Runs stays on the selected row. Linking tags
        Runs for filtering and does not grant coding, Git or repository access.
        This list does not Enable or Run now.
      </p>
      <div
        ref={listRef}
        className="worktree-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {agents.map((agent, i) => {
          const current = i === index;
          const shortId = agent.id.slice(0, 8);
          return (
            <article key={agent.id} {...itemProps(i, agent.id)}>
              <div className="row spread">
                <Link
                  className="text-link"
                  to={`/agents/${agent.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect agent ${agent.name} ${shortId}`}
                >
                  {agent.name}
                </Link>
                <span className="tiny-tag">
                  {agent.enabled ? "Enabled" : "Paused / draft"}
                </span>
              </div>
              <p className="muted">
                {agent.model || "No model selected"} · Last:{" "}
                {agent.last_status || "Never run"} · Next:{" "}
                {time(agent.next_run_at)}
              </p>
              {agent.goal ? <p className="agent-goal">{agent.goal}</p> : null}
              <Link
                className="text-link"
                to={`/runs?project_id=${projectId}&agent_id=${agent.id}`}
                tabIndex={current ? 0 : -1}
                aria-label={`View tagged Runs ${shortId}`}
              >
                View tagged Runs
              </Link>
            </article>
          );
        })}
      </div>
    </>
  );
}

export default function ProjectAgents({
  projectId,
  excludeAgentId,
}: {
  projectId: string;
  excludeAgentId?: string;
}) {
  const headingId = useId();
  const heading = excludeAgentId
    ? "Other agents on this project"
    : "Linked agents";
  const agents = useQuery({
    queryKey: ["project-agents", projectId],
    queryFn: () =>
      api<LinkedAgent[]>(
        `/agents?limit=50&offset=0&project_id=${encodeURIComponent(projectId)}`,
      ),
  });
  const rows = Array.isArray(agents.data)
    ? agents.data.filter((agent) => agent.id !== excludeAgentId)
    : [];
  return (
    <section className="panel content-panel mt" aria-labelledby={headingId}>
      <div className="row spread">
        <h2 id={headingId}>{heading}</h2>
        <Link
          className="text-link"
          to={`/agents?project_id=${projectId}`}
          aria-label="View all linked agents"
        >
          View all linked agents
        </Link>
      </div>
      <p className="muted">
        Definitions that tag their Runs with this project. Linking does not
        grant coding, Git or repository access. This list does not Enable or
        Run now.
      </p>
      <ErrorNotice error={agents.error} />
      {agents.isPending ? (
        <Loading />
      ) : rows.length ? (
        <AgentCards agents={rows} projectId={projectId} />
      ) : (
        <Empty
          title={
            excludeAgentId ? "No other linked agents" : "No linked agents"
          }
        >
          Link a project from Agents to tag those Runs for filtering.
        </Empty>
      )}
    </section>
  );
}
