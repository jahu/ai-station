import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";
import { AgentExecutionHistory } from "./AgentExecutionHistory";

type AgentDraft = {
  id: string;
  name: string;
  model: string;
  enabled: boolean;
  updated_at: string;
  goal?: string;
  system_prompt?: string;
  tools?: string[];
  skills?: string[];
  trigger?: string;
  cron_expr?: string | null;
  interval_seconds?: number | null;
  run_at?: string | null;
  require_approval?: boolean;
  workflow_mode?: string;
  tool_calling?: boolean | string;
  search_query?: string;
  fetch_urls?: string[];
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string;
  runs?: Run[];
};

function scheduleLabel(agent: AgentDraft) {
  if (agent.trigger === "cron") return `${agent.cron_expr} (UTC)`;
  if (agent.trigger === "interval")
    return `Every ${agent.interval_seconds} seconds`;
  if (agent.trigger === "datetime") return `Once: ${agent.run_at}`;
  return "Manual";
}

export function AssistantAgentDraft({
  agentId,
  tabIndex = 0,
}: {
  agentId: string;
  tabIndex?: number;
}) {
  const cache = useQueryClient();
  const shortId = agentId.slice(0, 8);
  const detail = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => api<AgentDraft>(`/agents/${agentId}`),
    refetchInterval: 3000,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api<AgentDraft>(`/agents/${agentId}/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_updated_at: detail.data!.updated_at,
          enabled,
        }),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["agent", agentId], (previous?: AgentDraft) => ({
        ...previous,
        ...result,
        runs: previous?.runs ?? result.runs ?? [],
      }));
      void cache.invalidateQueries({ queryKey: ["agent", agentId] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
    },
  });
  const agent = detail.data;
  const enableLabel = agent?.enabled
    ? `Pause agent ${shortId}`
    : `Enable saved definition ${shortId}`;
  const instructions = (agent?.goal || agent?.system_prompt || "").trim();
  const waiting = agent?.runs?.find(
    (run) => run.status === "waiting_for_approval",
  );
  const history = agent?.runs ?? [];
  return (
    <div className="assistant-agent-draft">
      <ErrorNotice error={detail.error ?? toggle.error} />
      {agent && (
        <>
          <p>
            <strong>{agent.name}</strong>
            {agent.enabled ? " · Enabled" : " · Disabled draft"}
            {agent.model ? ` · ${agent.model}` : ""}
          </p>
          <dl className="assistant-agent-definition">
            <div>
              <dt>Schedule</dt>
              <dd>{scheduleLabel(agent)}</dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>
                {agent.tools?.length ? agent.tools.join(", ") : "No tools"}
              </dd>
            </div>
            {agent.skills?.length ? (
              <div>
                <dt>Skills</dt>
                <dd>{agent.skills.join(", ")}</dd>
              </div>
            ) : null}
            {agent.search_query ? (
              <div>
                <dt>Public search query</dt>
                <dd>{agent.search_query}</dd>
              </div>
            ) : null}
            {agent.fetch_urls?.length ? (
              <div>
                <dt>Reviewed URLs</dt>
                <dd>{agent.fetch_urls.join(", ")}</dd>
              </div>
            ) : null}
            {agent.require_approval ? (
              <div>
                <dt>Approval</dt>
                <dd>Required before each Run</dd>
              </div>
            ) : null}
            {agent.workflow_mode === "gated" ? (
              <div>
                <dt>Workflow</dt>
                <dd>Gated</dd>
              </div>
            ) : null}
            {agent.tool_calling === true || agent.tool_calling === "bounded" ? (
              <div>
                <dt>Tool calling</dt>
                <dd>Bounded registry tools during the report</dd>
              </div>
            ) : null}
            {instructions ? (
              <div>
                <dt>Instructions</dt>
                <dd>
                  <pre className="assistant-agent-instructions">
                    {instructions}
                  </pre>
                </dd>
              </div>
            ) : null}
            <div>
              <dt>Next run</dt>
              <dd>{time(agent.next_run_at ?? null)}</dd>
            </div>
            <div>
              <dt>Last run</dt>
              <dd>
                {time(agent.last_run_at ?? null)}
                {agent.last_status ? ` · ${agent.last_status}` : ""}
              </dd>
            </div>
          </dl>
          {waiting ? (
            <p className="notice">
              A Run is waiting for approval.{" "}
              <Link
                to={`/runs/${waiting.id}`}
                tabIndex={tabIndex}
                aria-label={`Review waiting Run ${waiting.id.slice(0, 8)}`}
              >
                Review it
              </Link>
            </p>
          ) : null}
          <p className="muted">
            Activation stays explicit and uses the saved definition. It does not
            invent a conversation Run. Run now, tools and schedule stay in
            Agents.
          </p>
          <div className="row">
            <Button
              type="button"
              disabled={toggle.isPending}
              tabIndex={tabIndex}
              aria-label={enableLabel}
              onClick={() => toggle.mutate(!agent.enabled)}
            >
              {agent.enabled ? "Pause agent" : "Enable saved definition"}
            </Button>
            <Button asChild variant="secondary">
              <Link
                to={`/agents/${agentId}`}
                tabIndex={tabIndex}
                aria-label={`Review agent ${shortId}`}
              >
                Open in Agents
              </Link>
            </Button>
          </div>
          {history.length ? (
            <AgentExecutionHistory
              runs={history}
              tabIndex={tabIndex}
              hint="Arrow keys choose a Run while the list is focused. Enter inspects it. Run now stays in Agents."
            />
          ) : (
            <p className="muted">No executions yet. Run now stays in Agents.</p>
          )}
        </>
      )}
    </div>
  );
}
