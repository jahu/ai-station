import "./AssistantAgentDraft.css";
import {
  MarketEmailApproval,
  AgentMarketEmailHistory,
  AgentMarketRunStop,
  type MarketEmailAuthorization,
} from "./AgentMarketEmail";
import { AgentMarketEditor } from "./AgentMarketScope";
import { marketEmailConsentKey, type MarketScope } from "./marketScope";
import AgentWorkspacePolicy, {
  type WorkspacePolicy,
} from "./AgentWorkspacePolicy";
import AgentDataFiles, { type DataScope } from "./AgentDataFiles";
import AgentDataResult from "./AgentDataResult";
import GithubAgentScope from "./GithubAgentScope";
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
import { agentSettingsPayload, type AgentSettingsInput } from "./agentSettings";
import {
  ApprovalChoiceList,
  NoticeChoiceList,
  RetryChoiceList,
  ToolCallingChoiceList,
  WorkflowModeChoiceList,
} from "./AgentPolicyLists";
import { AgentLinkedProjectLinks, AgentProjectList } from "./AgentProjectList";
import LlamaModels from "./LlamaModels";
import ProjectAgents from "./ProjectAgents";

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
  data?: DataScope | null;
  market?: MarketScope | null;
  market_readiness?: { ready: boolean; reason: string | null } | null;
  market_email_authorization?: MarketEmailAuthorization | null;
  workspace_policy?: WorkspacePolicy;
  data_readiness?: { ready: boolean; reason: string } | null;
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
  github?: { connector_id: string; repository: string } | null;
  search_query?: string;
  fetch_urls?: string[];
  project_id?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string;
  runs?: Run[];
};

const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);

function scheduleLabel(agent: AgentDraft) {
  if (agent.trigger === "cron") return `${agent.cron_expr} (UTC)`;
  if (agent.trigger === "interval")
    return `Every ${agent.interval_seconds} seconds`;
  if (agent.trigger === "datetime") return `Once: ${agent.run_at}`;
  return "Manual";
}

type ScheduleTrigger = "manual" | "interval" | "cron" | "datetime";

function AgentSchedule({
  agentId,
  trigger,
  cronExpr,
  intervalSeconds,
  runAt,
  tabIndex,
  disabled,
  pending,
  onSave,
}: {
  agentId: string;
  trigger: string;
  cronExpr: string;
  intervalSeconds: number | null;
  runAt: string | null;
  tabIndex: number;
  disabled: boolean;
  pending: boolean;
  onSave: (patch: {
    trigger: ScheduleTrigger;
    cron_expr: string;
    interval_seconds: number | null;
    run_at: string | null;
  }) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const saved = trigger || "manual";
  const [nextTrigger, setNextTrigger] = useState<ScheduleTrigger>(
    saved === "interval" || saved === "cron" || saved === "datetime"
      ? saved
      : "manual",
  );
  const [cron, setCron] = useState(cronExpr);
  const [interval, setInterval] = useState(String(intervalSeconds ?? 3600));
  const [once, setOnce] = useState(runAt?.slice(0, 16) ?? "");
  const intervalValue = Number(interval);
  const nextRunAt = once ? `${once}:00Z` : null;
  const valid =
    nextTrigger === "manual" ||
    (nextTrigger === "cron" && cron.trim().split(/\s+/).length === 5) ||
    (nextTrigger === "interval" &&
      Number.isFinite(intervalValue) &&
      intervalValue >= 60 &&
      intervalValue <= 31536000) ||
    (nextTrigger === "datetime" && !!once);
  const unchanged =
    nextTrigger === saved &&
    (nextTrigger !== "cron" || cron.trim() === cronExpr) &&
    (nextTrigger !== "interval" ||
      intervalValue === (intervalSeconds ?? 3600)) &&
    (nextTrigger !== "datetime" || nextRunAt === runAt);
  return (
    <form
      className="assistant-agent-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || unchanged || disabled) return;
        onSave({
          trigger: nextTrigger,
          cron_expr: nextTrigger === "cron" ? cron.trim() : "",
          interval_seconds: nextTrigger === "interval" ? intervalValue : null,
          run_at: nextTrigger === "datetime" ? nextRunAt : null,
        });
      }}
    >
      <label>
        Schedule trigger
        <select
          value={nextTrigger}
          tabIndex={tabIndex}
          aria-label={`Schedule trigger ${shortId}`}
          disabled={disabled}
          onChange={(event) =>
            setNextTrigger(event.target.value as ScheduleTrigger)
          }
        >
          <option value="manual">Manual</option>
          <option value="interval">Interval</option>
          <option value="cron">Cron (UTC)</option>
          <option value="datetime">One-shot (UTC)</option>
        </select>
      </label>
      {nextTrigger === "interval" ? (
        <label>
          Interval seconds
          <input
            type="number"
            required
            min={60}
            max={31536000}
            value={interval}
            tabIndex={tabIndex}
            aria-label={`Interval seconds ${shortId}`}
            disabled={disabled}
            onChange={(event) => setInterval(event.target.value)}
          />
        </label>
      ) : null}
      {nextTrigger === "cron" ? (
        <label>
          Cron expression (UTC)
          <input
            required
            value={cron}
            tabIndex={tabIndex}
            aria-label={`Cron expression ${shortId}`}
            disabled={disabled}
            placeholder="0 8 * * *"
            onChange={(event) => setCron(event.target.value)}
          />
        </label>
      ) : null}
      {nextTrigger === "datetime" ? (
        <label>
          One-shot time (UTC)
          <input
            required
            type="datetime-local"
            value={once}
            tabIndex={tabIndex}
            aria-label={`One-shot time ${shortId}`}
            disabled={disabled}
            onChange={(event) => setOnce(event.target.value)}
          />
        </label>
      ) : null}
      <Button
        type="submit"
        variant="secondary"
        disabled={disabled || pending || !valid || unchanged}
        tabIndex={tabIndex}
        aria-label={`Save schedule ${shortId}`}
      >
        Save schedule
      </Button>
    </form>
  );
}

function parseFetchUrls(text: string) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function AgentSearchQuery({
  agentId,
  query,
  tabIndex,
  disabled,
  pending,
  onSave,
}: {
  agentId: string;
  query: string;
  tabIndex: number;
  disabled: boolean;
  pending: boolean;
  onSave: (query: string) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const [value, setValue] = useState(query);
  return (
    <form
      className="assistant-agent-search"
      onSubmit={(event) => {
        event.preventDefault();
        const next = value.trim();
        if (!next || next === query || disabled) return;
        onSave(next);
      }}
    >
      <label>
        Public search query
        <input
          required
          maxLength={500}
          value={value}
          tabIndex={tabIndex}
          aria-label={`Public search query ${shortId}`}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Exact public query sent to search"
        />
      </label>
      <Button
        type="submit"
        variant="secondary"
        disabled={
          disabled || pending || !value.trim() || value.trim() === query
        }
        tabIndex={tabIndex}
        aria-label={`Save public search query ${shortId}`}
      >
        Save public search query
      </Button>
    </form>
  );
}

function AgentFetchUrls({
  agentId,
  urls,
  tabIndex,
  disabled,
  pending,
  onSave,
}: {
  agentId: string;
  urls: string[];
  tabIndex: number;
  disabled: boolean;
  pending: boolean;
  onSave: (urls: string[]) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const saved = urls.join("\n");
  const [value, setValue] = useState(saved);
  const next = parseFetchUrls(value);
  return (
    <form
      className="assistant-agent-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (!next.length || next.join("\n") === saved || disabled) return;
        onSave(next);
      }}
    >
      <label>
        Reviewed URLs
        <textarea
          required
          rows={3}
          value={value}
          tabIndex={tabIndex}
          aria-label={`Reviewed URLs ${shortId}`}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          placeholder="https://www.example.com/"
        />
      </label>
      <Button
        type="submit"
        variant="secondary"
        disabled={
          disabled || pending || !next.length || next.join("\n") === saved
        }
        tabIndex={tabIndex}
        aria-label={`Save reviewed URLs ${shortId}`}
      >
        Save reviewed URLs
      </Button>
    </form>
  );
}

function AgentIdentity({
  agentId,
  name,
  maximumRuntime,
  outputExpectation,
  tabIndex,
  disabled,
  pending,
  onSave,
}: {
  agentId: string;
  name: string;
  maximumRuntime: number;
  outputExpectation: string;
  tabIndex: number;
  disabled: boolean;
  pending: boolean;
  onSave: (patch: {
    name: string;
    maximum_runtime: number;
    output_expectation: string;
  }) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const [nextName, setNextName] = useState(name);
  const [limit, setLimit] = useState(String(maximumRuntime));
  const [outcome, setOutcome] = useState(outputExpectation);
  const trimmedName = nextName.trim();
  const trimmedOutcome = outcome.trim();
  const runtime = Number(limit);
  const valid =
    trimmedName.length > 0 &&
    trimmedName.length <= 200 &&
    Number.isInteger(runtime) &&
    runtime >= 5 &&
    runtime <= 3600 &&
    trimmedOutcome.length <= 4000;
  const unchanged =
    trimmedName === name &&
    runtime === maximumRuntime &&
    trimmedOutcome === outputExpectation;
  return (
    <form
      className="assistant-agent-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || unchanged || disabled) return;
        onSave({
          name: trimmedName,
          maximum_runtime: runtime,
          output_expectation: trimmedOutcome,
        });
      }}
    >
      <label>
        Name
        <input
          required
          maxLength={200}
          value={nextName}
          tabIndex={tabIndex}
          aria-label={`Name ${shortId}`}
          disabled={disabled}
          onChange={(event) => setNextName(event.target.value)}
        />
      </label>
      <label>
        Time limit (seconds)
        <input
          type="number"
          required
          min={5}
          max={3600}
          value={limit}
          tabIndex={tabIndex}
          aria-label={`Time limit ${shortId}`}
          disabled={disabled}
          onChange={(event) => setLimit(event.target.value)}
        />
      </label>
      <label>
        Expected outcome
        <textarea
          maxLength={4000}
          rows={2}
          value={outcome}
          tabIndex={tabIndex}
          aria-label={`Expected outcome ${shortId}`}
          disabled={disabled}
          onChange={(event) => setOutcome(event.target.value)}
        />
      </label>
      <Button
        type="submit"
        variant="secondary"
        disabled={disabled || pending || !valid || unchanged}
        tabIndex={tabIndex}
        aria-label={`Save identity ${shortId}`}
      >
        Save identity
      </Button>
    </form>
  );
}

function AgentDescription({
  agentId,
  description,
  tabIndex,
  disabled,
  pending,
  onSave,
}: {
  agentId: string;
  description: string;
  tabIndex: number;
  disabled: boolean;
  pending: boolean;
  onSave: (patch: { description: string }) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const [next, setNext] = useState(description);
  const trimmed = next.trim();
  const valid = trimmed.length <= 4000;
  const unchanged = trimmed === description;
  return (
    <form
      className="assistant-agent-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || unchanged || disabled) return;
        onSave({ description: trimmed });
      }}
    >
      <label>
        Description
        <textarea
          maxLength={4000}
          rows={2}
          value={next}
          tabIndex={tabIndex}
          aria-label={`Description ${shortId}`}
          disabled={disabled}
          onChange={(event) => setNext(event.target.value)}
        />
      </label>
      <Button
        type="submit"
        variant="secondary"
        disabled={disabled || pending || !valid || unchanged}
        tabIndex={tabIndex}
        aria-label={`Save description ${shortId}`}
      >
        Save description
      </Button>
    </form>
  );
}

function AgentInstructions({
  agentId,
  goal,
  systemPrompt,
  tabIndex,
  disabled,
  pending,
  onSave,
}: {
  agentId: string;
  goal: string;
  systemPrompt: string;
  tabIndex: number;
  disabled: boolean;
  pending: boolean;
  onSave: (patch: { goal: string; system_prompt: string }) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const [nextGoal, setNextGoal] = useState(goal);
  const [prompt, setPrompt] = useState(systemPrompt);
  const trimmedGoal = nextGoal.trim();
  const trimmedPrompt = prompt.trim();
  const valid = trimmedGoal.length > 0 && trimmedGoal.length <= 16000;
  const unchanged = trimmedGoal === goal && trimmedPrompt === systemPrompt;
  return (
    <form
      className="assistant-agent-search"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || unchanged || disabled) return;
        onSave({ goal: trimmedGoal, system_prompt: trimmedPrompt });
      }}
    >
      <label>
        Goal
        <textarea
          required
          maxLength={16000}
          rows={3}
          value={nextGoal}
          tabIndex={tabIndex}
          aria-label={`Goal ${shortId}`}
          disabled={disabled}
          onChange={(event) => setNextGoal(event.target.value)}
        />
      </label>
      <label>
        System prompt
        <textarea
          maxLength={8000}
          rows={3}
          value={prompt}
          tabIndex={tabIndex}
          aria-label={`System prompt ${shortId}`}
          disabled={disabled}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </label>
      <Button
        type="submit"
        variant="secondary"
        disabled={disabled || pending || !valid || unchanged}
        tabIndex={tabIndex}
        aria-label={`Save instructions ${shortId}`}
      >
        Save instructions
      </Button>
    </form>
  );
}

export function AssistantAgentDraft({
  agentId,
  tabIndex = 0,
  compact = false,
}: {
  agentId: string;
  tabIndex?: number;
  compact?: boolean;
}) {
  const cache = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [emailConsent, setEmailConsent] = useState<string | null>(null);
  const [emailReady, setEmailReady] = useState(false);
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
          ...(enabled && detail.data?.market?.email
            ? {
                confirm_market_email:
                  emailConsent ===
                  marketEmailConsentKey(detail.data.id, detail.data.market),
              }
            : {}),
        }),
      }),
    onSuccess: (result) => {
      setEmailConsent(null);
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
    queryFn: () => api<unknown>("/agents/tools"),
  });
  const skillsCatalog = useQuery({
    queryKey: ["skills"],
    queryFn: () => api<unknown>("/skills"),
  });
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ id: string; name: string }[]>("/projects?limit=500"),
  });
  const saveSettings = useMutation({
    mutationFn: (patch: Partial<AgentSettingsInput>) =>
      api<AgentDraft>(`/agents/${agentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          agentSettingsPayload(detail.data!, {
            ...patch,
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
  const localModels = useQuery({
    queryKey: ["llama-models"],
    queryFn: () => api<{ models: { id: string; name: string }[] }>("/llama"),
    enabled: compact && !!detail.data?.model.startsWith("llamacpp:"),
  });
  const agent = detail.data;
  const block = agent
    ? activationBlock(agent, catalog.data, skillsCatalog.data)
    : { blocked: false, reason: null };
  const enableLabel = agent?.enabled
    ? `Pause agent ${shortId}`
    : `Enable saved definition ${shortId}`;
  const waiting = agent?.runs?.find(
    (run) => run.status === "waiting_for_approval",
  );
  const history = agent?.runs ?? [];
  const busy =
    toggle.isPending ||
    duplicate.isPending ||
    runNow.isPending ||
    saveSettings.isPending ||
    modelBusy;
  const active = history.some((run) => !TERMINAL.has(run.status));
  if (compact && !expanded) {
    const external = agent?.tools?.some((tool) =>
      ["coding_cursor", "coding_codex"].includes(tool),
    );
    const modelName = external
      ? `${agent?.tools?.includes("coding_cursor") ? "Cursor" : "Codex"} · CLI default`
      : agent?.model === "auto"
        ? "Auto · local coding"
        : agent?.tools?.includes("market_watch")
          ? "No model needed"
          : agent?.model.startsWith("llamacpp:")
            ? (localModels.data?.models.find(
                (item) => item.id === agent.model.slice(9),
              )?.name ?? "Local llama.cpp model")
            : agent?.model || "Choose a local model";
    const interval = agent?.interval_seconds ?? 0;
    const daily =
      agent?.trigger === "cron"
        ? /^(\d{1,2}) (\d{1,2}) \* \* \*$/.exec(agent.cron_expr ?? "")
        : null;
    const cadence = !agent
      ? ""
      : agent.trigger === "interval" && interval > 0
        ? interval % 3600 === 0
          ? `Every ${interval / 3600} ${interval === 3600 ? "hour" : "hours"}`
          : interval % 60 === 0
            ? `Every ${interval / 60} ${interval === 60 ? "minute" : "minutes"}`
            : `Every ${interval} seconds`
        : daily
          ? `Daily at ${daily[2].padStart(2, "0")}:${daily[1].padStart(2, "0")} UTC`
          : agent.trigger === "cron"
            ? "Custom UTC schedule"
            : scheduleLabel(agent);
    return (
      <section
        className="assistant-agent-brief"
        aria-label="Agent draft summary"
      >
        <ErrorNotice error={detail.error ?? runNow.error} />
        {agent ? (
          <>
            <div className="assistant-agent-brief-head">
              <h3>{agent.name}</h3>
              <span className="assistant-agent-brief-status">
                {agent.enabled ? "Enabled" : "Disabled draft"}
              </span>
            </div>
            <p className="assistant-agent-brief-goal">
              {agent.goal || agent.description}
            </p>
            <dl className="assistant-agent-brief-facts">
              <div>
                <dt>Execution</dt>
                <dd>
                  {external ? "External coding" : "Local"} · {modelName}
                </dd>
              </div>
              <div>
                <dt>Schedule</dt>
                <dd title={agent.cron_expr ?? undefined}>{cadence}</dd>
              </div>
              <div>
                <dt>Tools</dt>
                <dd>
                  {agent.tools?.length
                    ? agent.tools
                        .map((tool) => tool.replaceAll("_", " "))
                        .join(" · ")
                    : "No tools selected"}
                </dd>
              </div>
              {agent.search_query && (
                <div>
                  <dt>Public search query</dt>
                  <dd>{agent.search_query}</dd>
                </div>
              )}
              {agent.fetch_urls?.length ? (
                <div>
                  <dt>Reviewed pages</dt>
                  <dd>{agent.fetch_urls.join(" · ")}</dd>
                </div>
              ) : null}
            </dl>
            {!agent.enabled && (
              <p className="muted assistant-agent-brief-note">
                {history.length || agent.last_run_at
                  ? "Paused. Previous results and history remain in the agent workspace."
                  : "Review its instructions and scope before enabling. No agent work has started."}
              </p>
            )}
            <div className="assistant-agent-brief-actions">
              <Button asChild>
                <Link
                  tabIndex={tabIndex}
                  to={`/agents/${agent.id}?view=${agent.enabled ? "workspace" : "settings"}`}
                >
                  {agent.enabled ? "Open agent workspace" : "Review & enable"}
                </Link>
              </Button>
              {agent.enabled && (
                <Button
                  type="button"
                  variant="secondary"
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  onClick={() => runNow.mutate()}
                >
                  Run now
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                tabIndex={tabIndex}
                onClick={() => setExpanded(true)}
              >
                Edit in conversation
              </Button>
            </div>
            {history.length ? (
              agent.tools?.includes("python_data") ? (
                <AgentDataResult runs={history} />
              ) : (
                <AgentLatestReport runs={history} />
              )
            ) : null}
          </>
        ) : !detail.error ? (
          <p className="muted" role="status">
            Loading the saved agent…
          </p>
        ) : null}
      </section>
    );
  }
  return (
    <div className="assistant-agent-draft">
      {compact && (
        <Button
          type="button"
          variant="ghost"
          tabIndex={tabIndex}
          onClick={() => setExpanded(false)}
        >
          Back to summary
        </Button>
      )}
      <ErrorNotice
        error={
          detail.error ??
          toggle.error ??
          duplicate.error ??
          runNow.error ??
          saveSettings.error ??
          provider.error ??
          skillsCatalog.error ??
          projects.error
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
              <dt>Identity</dt>
              <dd>
                <AgentIdentity
                  key={agent.updated_at}
                  agentId={agent.id}
                  name={agent.name}
                  maximumRuntime={agent.maximum_runtime ?? 600}
                  outputExpectation={agent.output_expectation ?? ""}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  pending={saveSettings.isPending}
                  onSave={(patch) => saveSettings.mutate(patch)}
                />
              </dd>
            </div>
            <div>
              <dt>Description</dt>
              <dd>
                <AgentDescription
                  key={agent.updated_at}
                  agentId={agent.id}
                  description={agent.description ?? ""}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  pending={saveSettings.isPending}
                  onSave={(patch) => saveSettings.mutate(patch)}
                />
              </dd>
            </div>
            <div>
              <dt>Linked project</dt>
              <dd>
                <AgentProjectList
                  automaticWorkspace={
                    agent.tools?.includes("coding_local") ||
                    agent.tools?.includes("python_data")
                  }
                  key={agent.updated_at}
                  agentId={agent.id}
                  projectId={agent.project_id ?? null}
                  projects={projects.data ?? []}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  onSave={(project_id) => saveSettings.mutate({ project_id })}
                />
                <AgentLinkedProjectLinks
                  agentId={agent.id}
                  projectId={agent.project_id ?? null}
                  projectName={
                    projects.data?.find((item) => item.id === agent.project_id)
                      ?.name
                  }
                  tabIndex={tabIndex}
                />
                {agent.project_id ? (
                  <ProjectAgents
                    projectId={agent.project_id}
                    excludeAgentId={agent.id}
                  />
                ) : null}
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>
                {agent.tools?.includes("market_watch") ? (
                  <span>Deterministic · no model or GPU</span>
                ) : (
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
                      saveSettings.mutate({ model });
                    }}
                  />
                )}
              </dd>
            </div>
            <div>
              <dt>Schedule</dt>
              <dd>
                <p>{scheduleLabel(agent)}</p>
                <AgentSchedule
                  key={agent.updated_at}
                  agentId={agent.id}
                  trigger={agent.trigger ?? "manual"}
                  cronExpr={agent.cron_expr ?? ""}
                  intervalSeconds={agent.interval_seconds ?? null}
                  runAt={agent.run_at ?? null}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  pending={saveSettings.isPending}
                  onSave={(patch) => saveSettings.mutate(patch)}
                />
              </dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>
                <AgentAttachedTools
                  names={agent.tools ?? []}
                  agentId={agent.id}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  pending={saveSettings.isPending}
                  onRemove={(name) =>
                    saveSettings.mutate({
                      tools: (agent.tools ?? []).filter(
                        (tool) => tool !== name,
                      ),
                      ...(name === "python_data" ? { data: null } : {}),
                    })
                  }
                  onAdd={(name) => {
                    if ((agent.tools ?? []).includes(name)) return;
                    saveSettings.mutate(
                      name === "python_data"
                        ? {
                            tools: [name],
                            model: "auto",
                            data: null,
                            permission_profile: "agent_local",
                            tool_calling: "none",
                          }
                        : {
                            tools: [...(agent.tools ?? []), name],
                          },
                    );
                  }}
                />
                {agent.tools?.includes("remember_report") ? (
                  <p
                    className="notice"
                    role="note"
                    aria-label={`Report memory ${shortId}`}
                  >
                    Successful reports will be stored in this agent’s memory
                    with their source Run. They are observations, not verified
                    facts. Select memory_search to use them on future runs. You
                    can edit, disable or delete them in Memory.
                  </p>
                ) : null}
                {agent.tools?.includes("remember_workflow") ? (
                  <p
                    className="notice"
                    role="note"
                    aria-label={`Workflow memory ${shortId}`}
                  >
                    Successful telemetry, public search and HTTP fetch steps
                    will be stored in this agent’s memory with their source Run.
                    memory_search results are not copied. Failures and
                    cancellation write nothing. Select memory_search to use them
                    on future runs.
                  </p>
                ) : null}
              </dd>
            </div>
            <div>
              <dt>Skills</dt>
              <dd>
                <AgentAttachedSkills
                  ids={agent.skills ?? []}
                  agentId={agent.id}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  pending={saveSettings.isPending}
                  onRemove={(id) =>
                    saveSettings.mutate({
                      skills: (agent.skills ?? []).filter(
                        (skill) => skill !== id,
                      ),
                    })
                  }
                  onAdd={(id) => {
                    if ((agent.skills ?? []).includes(id)) return;
                    saveSettings.mutate({
                      skills: [...(agent.skills ?? []), id],
                    });
                  }}
                />
              </dd>
            </div>
            {agent.tools?.includes("python_data") && (
              <div>
                <dt>Data inputs</dt>
                <dd>
                  <AgentDataFiles
                    value={agent.data}
                    disabled={busy || active}
                    onChange={(data) => saveSettings.mutate({ data })}
                  />
                </dd>
              </div>
            )}
            {agent.tools?.includes("github_read") ? (
              <div>
                <dt>Reviewed GitHub repository</dt>
                <dd>
                  <GithubAgentScope
                    value={agent.github ?? null}
                    disabled={busy || active || saveSettings.isPending}
                    onChange={(github) => saveSettings.mutate({ github })}
                  />
                </dd>
              </div>
            ) : null}
            {agent.tools?.includes("web_search") ? (
              <div>
                <dt>Public search query</dt>
                <dd>
                  <AgentSearchQuery
                    key={agent.updated_at}
                    agentId={agent.id}
                    query={agent.search_query ?? ""}
                    tabIndex={tabIndex}
                    disabled={busy || active}
                    pending={saveSettings.isPending}
                    onSave={(search_query) =>
                      saveSettings.mutate({ search_query })
                    }
                  />
                </dd>
              </div>
            ) : null}
            {agent.tools?.includes("http_fetch") ||
            agent.tools?.includes("browser") ? (
              <div>
                <dt>Reviewed URLs</dt>
                <dd>
                  <AgentFetchUrls
                    key={agent.updated_at}
                    agentId={agent.id}
                    urls={agent.fetch_urls ?? []}
                    tabIndex={tabIndex}
                    disabled={busy || active}
                    pending={saveSettings.isPending}
                    onSave={(fetch_urls) => saveSettings.mutate({ fetch_urls })}
                  />
                </dd>
              </div>
            ) : null}
            <div>
              <dt>Approval</dt>
              <dd>
                <ApprovalChoiceList
                  checked={Boolean(agent.require_approval)}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  onChange={(require_approval) => {
                    if (require_approval === Boolean(agent.require_approval))
                      return;
                    saveSettings.mutate({ require_approval });
                  }}
                />
              </dd>
            </div>
            <div>
              <dt>Workflow</dt>
              <dd>
                <WorkflowModeChoiceList
                  mode={
                    agent.workflow_mode === "gated" ? "gated" : "sequential"
                  }
                  name={`workflow_mode_${shortId}`}
                  tabIndex={tabIndex}
                  disabled={
                    busy || active || agent.tools?.includes("market_watch")
                  }
                  onChange={(workflow_mode) => {
                    const current =
                      agent.workflow_mode === "gated" ? "gated" : "sequential";
                    if (workflow_mode === current) return;
                    saveSettings.mutate({ workflow_mode });
                  }}
                />
              </dd>
            </div>
            <div>
              <dt>Tool calling</dt>
              <dd>
                <ToolCallingChoiceList
                  mode={
                    agent.tool_calling === true ||
                    agent.tool_calling === "bounded"
                      ? "bounded"
                      : "none"
                  }
                  tabIndex={tabIndex}
                  disabled={
                    busy || active || agent.tools?.includes("market_watch")
                  }
                  onChange={(tool_calling) => {
                    const current =
                      agent.tool_calling === true ||
                      agent.tool_calling === "bounded"
                        ? "bounded"
                        : "none";
                    if (tool_calling === current) return;
                    saveSettings.mutate({ tool_calling });
                  }}
                />
              </dd>
            </div>
            <div>
              <dt>Retry</dt>
              <dd>
                <RetryChoiceList
                  mode={
                    agent.retry_policy?.mode === "manual" ? "manual" : "none"
                  }
                  name={`retry_policy_${shortId}`}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  onChange={(mode) => {
                    const current =
                      agent.retry_policy?.mode === "manual" ? "manual" : "none";
                    if (mode === current) return;
                    saveSettings.mutate({ retry_policy: { mode } });
                  }}
                />
              </dd>
            </div>
            <div>
              <dt>Notices</dt>
              <dd>
                <NoticeChoiceList
                  policy={{
                    on_success: agent.notification_policy?.on_success === true,
                    on_failure: agent.notification_policy?.on_failure === true,
                    on_approval:
                      agent.notification_policy?.on_approval === true,
                  }}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  onChange={(notification_policy) => {
                    const current = {
                      on_success:
                        agent.notification_policy?.on_success === true,
                      on_failure:
                        agent.notification_policy?.on_failure === true,
                      on_approval:
                        agent.notification_policy?.on_approval === true,
                    };
                    if (
                      notification_policy.on_success === current.on_success &&
                      notification_policy.on_failure === current.on_failure &&
                      notification_policy.on_approval === current.on_approval
                    )
                      return;
                    saveSettings.mutate({ notification_policy });
                  }}
                />
              </dd>
            </div>
            <div>
              <dt>Instructions</dt>
              <dd>
                <AgentInstructions
                  key={agent.updated_at}
                  agentId={agent.id}
                  goal={agent.goal ?? ""}
                  systemPrompt={agent.system_prompt ?? ""}
                  tabIndex={tabIndex}
                  disabled={busy || active}
                  pending={saveSettings.isPending}
                  onSave={(patch) => saveSettings.mutate(patch)}
                />
              </dd>
            </div>
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
          {agent.tools?.includes("market_watch") && (
            <AgentMarketEditor
              key={agent.updated_at}
              value={agent.market}
              disabled={busy || active}
              onSave={(market) => saveSettings.mutate({ market })}
            />
          )}
          {agent.tools?.includes("coding_local") && (
            <AgentWorkspacePolicy
              value={agent.workspace_policy}
              linkedProject={agent.project_id}
              disabled={busy || active}
              onChange={(workspace_policy) =>
                saveSettings.mutate({ workspace_policy })
              }
            />
          )}
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
            definition and does not call Enable. Saving a public search query or
            reviewed URLs stores those values on the definition and does not
            call Enable. Removing an unavailable tool or a missing skill stores
            the remaining list on the definition and does not call Enable.
            Adding an operational registry tool stores it on the definition and
            does not call Enable. Unpublished adapters cannot be added. Attached
            remember-reports or remember-workflow tools show how observations
            are stored and do not invent a Run. Adding an installed skill stores
            it on the definition and does not call Enable. At most four skills.
            Enable stays off until the saved definition can activate. Duplicate
            as draft stays disabled. Run now queues a new workflow from that
            saved definition and stays on this transcript. A waiting Run can
            Approve and queue or Deny here without opening the inspector. Stop
            stays on an in-progress history Run. Manual retry queues a new
            workflow from a failed snapshot. Saving a schedule stores it on the
            definition and does not call Enable. Saving approval, retry, notice,
            workflow or bounded tool calling policies stores them on the
            definition and does not call Enable. Saving instructions stores the
            goal and system prompt on the definition and does not call Enable.
            Saving identity stores the name, time limit and expected outcome on
            the definition and does not call Enable. Saving description stores
            that text on the definition and does not call Enable. Saving a
            linked project stores it on the definition and does not call Enable.
            Other agents on that same project stay next to that link and do not
            Enable or Run now.
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
          <MarketEmailApproval
            market={agent.market}
            enabled={agent.enabled}
            authorization={agent.market_email_authorization}
            checked={
              emailConsent === marketEmailConsentKey(agent.id, agent.market)
            }
            onChange={(checked) =>
              setEmailConsent(
                checked ? marketEmailConsentKey(agent.id, agent.market) : null,
              )
            }
            onReadyChange={setEmailReady}
          />
          <div className="row">
            <Button
              type="button"
              disabled={
                busy ||
                block.blocked ||
                (!agent.enabled &&
                  !!agent.market?.email &&
                  (!emailReady ||
                    emailConsent !==
                      marketEmailConsentKey(agent.id, agent.market)))
              }
              tabIndex={tabIndex}
              aria-label={
                !agent.enabled && agent.market?.email
                  ? `Enable and allow alert email ${shortId}`
                  : enableLabel
              }
              onClick={() => toggle.mutate(!agent.enabled)}
            >
              {agent.enabled
                ? "Pause agent"
                : agent.market?.email
                  ? "Enable and allow alert email"
                  : "Enable saved definition"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={
                busy ||
                !agent.enabled ||
                active ||
                (!!agent.market?.email &&
                  !agent.market_email_authorization?.valid)
              }
              tabIndex={tabIndex}
              aria-label={`Run now ${shortId}`}
              onClick={() => runNow.mutate()}
            >
              Run now
            </Button>
            {agent.tools?.includes("market_watch") && (
              <AgentMarketRunStop agentId={agent.id} runs={history} />
            )}
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
              {agent.tools?.includes("python_data") ? (
                <AgentDataResult runs={history} />
              ) : (
                <>
                  {(agent.market ||
                    history.some(
                      (run) => run.executor_type === "email_send",
                    )) && (
                    <AgentMarketEmailHistory
                      agentId={agent.id}
                      runs={history}
                    />
                  )}
                  <AgentLatestReport runs={history} />
                </>
              )}
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
