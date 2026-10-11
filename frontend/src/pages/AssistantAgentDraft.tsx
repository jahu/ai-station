import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";
import {
  AgentExecutionHistory,
  RunApprovalActions,
} from "./AgentExecutionHistory";
import { AgentLatestReport } from "./AgentLatestReport";
import { AgentAttachedSkills } from "./AgentAttachedSkills";
import { AgentAttachedTools } from "./AgentAttachedTools";
import { AgentLastWorkflowSteps } from "./AgentWorkflowSteps";
import { activationBlock } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";
import LlamaModels from "./LlamaModels";

type AgentDraft = {
  id: string;
  name: string;
  description?: string;
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
  maximum_runtime?: number;
  output_expectation?: string;
  require_approval?: boolean;
  workflow_mode?: string;
  tool_calling?: boolean | string;
  retry_policy?: { mode?: string };
  notification_policy?: {
    on_success?: boolean;
    on_failure?: boolean;
    on_approval?: boolean;
  };
  search_query?: string;
  fetch_urls?: string[];
  project_id?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string;
  runs?: Run[];
};

const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);

function noticeLabel(policy: AgentDraft["notification_policy"]) {
  if (!policy) return "";
  return [
    policy.on_failure ? "failure or interruption" : "",
    policy.on_success ? "success" : "",
    policy.on_approval ? "waiting for approval" : "",
  ]
    .filter(Boolean)
    .join(", ");
}

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
  const [copy, setCopy] = useState<AgentDraft | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
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
  const duplicate = useMutation({
    mutationFn: () =>
      api<AgentDraft>(`/agents/${agentId}/duplicate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_updated_at: detail.data!.updated_at,
        }),
      }),
    onSuccess: (result) => {
      setCopy(result);
      void cache.invalidateQueries({ queryKey: ["agents"] });
    },
  });
  const runNow = useMutation({
    mutationFn: () =>
      api<Run>(`/agents/${agentId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_updated_at: detail.data!.updated_at,
        }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["agent", agentId] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      void cache.invalidateQueries({ queryKey: ["conversation"] });
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const catalog = useQuery({
    queryKey: ["agent-tools"],
    enabled: !!detail.data?.tools?.length,
    queryFn: () => api<unknown>("/agents/tools"),
  });
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
  });
  const saveModel = useMutation({
    mutationFn: (model: string) =>
      api<AgentDraft>(`/agents/${agentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          agentSettingsPayload(detail.data!, {
            model,
            enabled: detail.data!.enabled,
          }),
        ),
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
  const block = agent
    ? activationBlock(agent, catalog.data)
    : { blocked: false, reason: null };
  const enableLabel = agent?.enabled
    ? `Pause agent ${shortId}`
    : `Enable saved definition ${shortId}`;
  const instructions = (agent?.goal || agent?.system_prompt || "").trim();
  const waiting = agent?.runs?.find(
    (run) => run.status === "waiting_for_approval",
  );
  const history = agent?.runs ?? [];
  const busy =
    toggle.isPending ||
    duplicate.isPending ||
    runNow.isPending ||
    saveModel.isPending ||
    modelBusy;
  const active = history.some((run) => !TERMINAL.has(run.status));
  return (
    <div className="assistant-agent-draft">
      <ErrorNotice
        error={
          detail.error ??
          toggle.error ??
          duplicate.error ??
          runNow.error ??
          saveModel.error ??
          provider.error
        }
      />
      {agent && (
        <>
          <p>
            <strong>{agent.name}</strong>
            {agent.enabled ? " · Enabled" : " · Disabled draft"}
          </p>
          <dl className="assistant-agent-definition">
            <div>
              <dt>Model</dt>
              <dd>
                <LlamaModels
                  compact
                  value={agent.model}
                  models={provider.data?.models ?? []}
                  triggerLabel={`Saved model ${shortId}`}
                  tabIndex={tabIndex}
                  busy={busy || active}
                  onBusy={setModelBusy}
                  onSelect={(model) => {
                    if (model === agent.model || active) return;
                    saveModel.mutate(model);
                  }}
                />
              </dd>
            </div>
            <div>
              <dt>Schedule</dt>
              <dd>{scheduleLabel(agent)}</dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>
                {agent.tools?.length ? (
                  <AgentAttachedTools names={agent.tools} tabIndex={tabIndex} />
                ) : (
                  "No tools"
                )}
              </dd>
            </div>
            {agent.skills?.length ? (
              <div>
                <dt>Skills</dt>
                <dd>
                  <AgentAttachedSkills ids={agent.skills} tabIndex={tabIndex} />
                </dd>
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
            {agent.retry_policy?.mode === "manual" ? (
              <div>
                <dt>Retry</dt>
                <dd>Manual retry of a failed snapshot</dd>
              </div>
            ) : null}
            {noticeLabel(agent.notification_policy) ? (
              <div>
                <dt>Notices</dt>
                <dd>
                  In-app notices on {noticeLabel(agent.notification_policy)}
                </dd>
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
            <div className="assistant-agent-approval">
              <p className="notice">
                A Run is waiting for approval. Granting queues it for the
                worker; tools and inference have not started. Deny cancels it.
                That does not call Run now.
              </p>
              <div className="row">
                <RunApprovalActions
                  runId={waiting.id}
                  name="waiting Run"
                  tabIndex={tabIndex}
                />
                <Button asChild variant="secondary">
                  <Link
                    to={`/runs/${waiting.id}`}
                    tabIndex={tabIndex}
                    aria-label={`Review waiting Run ${waiting.id.slice(0, 8)}`}
                  >
                    Review it
                  </Link>
                </Button>
              </div>
            </div>
          ) : null}
          <p className="muted">
            Activation stays explicit and uses the saved definition. It does not
            invent a conversation Run. Use model saves a local model on that
            definition and does not call Enable. Enable stays off until the
            saved definition can activate. Duplicate as draft stays disabled.
            Run now queues a new workflow from that saved definition and stays
            on this transcript. A waiting Run can Approve and queue or Deny here
            without opening the inspector. Stop stays on an in-progress history
            Run. Manual retry queues a new workflow from a failed snapshot.
            Tools and schedule stay in Agents.
          </p>
          {copy ? (
            <p>
              Copied as disabled draft <strong>{copy.name}</strong>.{" "}
              <Link
                to={`/agents/${copy.id}`}
                tabIndex={tabIndex}
                aria-label={`Review copy ${copy.id.slice(0, 8)}`}
              >
                Open copy in Agents
              </Link>
            </p>
          ) : null}
          {block.reason ? <p className="notice">{block.reason}</p> : null}
          <div className="row">
            <Button
              type="button"
              disabled={busy || block.blocked}
              tabIndex={tabIndex}
              aria-label={enableLabel}
              onClick={() => toggle.mutate(!agent.enabled)}
            >
              {agent.enabled ? "Pause agent" : "Enable saved definition"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={busy || !agent.enabled || active}
              tabIndex={tabIndex}
              aria-label={`Run now ${shortId}`}
              onClick={() => runNow.mutate()}
            >
              Run now
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              tabIndex={tabIndex}
              aria-label={`Duplicate as draft ${shortId}`}
              onClick={() => duplicate.mutate()}
            >
              Duplicate as draft
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
            <Button asChild variant="secondary">
              <Link
                to={`/memory?scope=agent&scope_id=${agentId}`}
                tabIndex={tabIndex}
                aria-label={`Inspect agent memory ${shortId}`}
              >
                Inspect this agent's memory
              </Link>
            </Button>
          </div>
          {history.length ? (
            <>
              <AgentLatestReport runs={history} />
              <AgentLastWorkflowSteps runs={history} tabIndex={tabIndex} />
              <AgentExecutionHistory
                runs={history}
                tabIndex={tabIndex}
                hint="Arrow keys choose a Run while the list is focused. Enter inspects it. Stop stays on an in-progress Run. Approve and queue or Deny stays on a waiting Run. Retry as a new workflow stays on a failed snapshot when the saved policy allows it. The latest report and its recorded search sources, fetched pages and registry tool calls stay here. Workflow steps of the last parent stay next to this history. Run now stays on the saved definition."
              />
            </>
          ) : (
            <p className="muted">
              No executions yet. Run now queues a new workflow from the saved
              definition.
            </p>
          )}
        </>
      )}
    </div>
  );
}
