import AgentDraftForm from "./AgentDraftForm";
import {
  MarketEmailApproval,
  AgentMarketEmailHistory,
  AgentMarketRunStop,
  type MarketEmailAuthorization,
} from "./AgentMarketEmail";
import AgentMarketScope from "./AgentMarketScope";
import {
  DEFAULT_MARKET,
  marketEmailConsentKey,
  type MarketScope,
} from "./marketScope";
import AgentWorkspacePolicy, {
  type WorkspacePolicy,
} from "./AgentWorkspacePolicy";
import AgentDataFiles, { type DataScope } from "./AgentDataFiles";
import AgentMediaScopeEditor from "./AgentMediaScope";
import AgentMediaResult from "./AgentMediaResult";
import {
  agentMediaIssue,
  fixedAgentMedia,
  newAgentMedia,
  type AgentMediaScope,
} from "./agent-media";
import AgentDataResult from "./AgentDataResult";
import AgentCodeWorkspace from "./AgentCodeWorkspace";
import { useId, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api, type Run } from "../api";
import { Empty, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import LlamaModels from "./LlamaModels";
import { time } from "../lib/utils";
import {
  AgentExecutionHistory,
  RunApprovalActions,
} from "./AgentExecutionHistory";
import { AgentLatestReport } from "./AgentLatestReport";
import { AgentLastWorkflowSteps } from "./AgentWorkflowSteps";
import GithubAgentScope from "./GithubAgentScope";
import { useListKeyboard } from "./useListKeyboard";
import { activationBlock } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";
import { AgentLinkedProjectLinks, AgentProjectList } from "./AgentProjectList";
import ProjectAgents from "./ProjectAgents";
import {
  ApprovalChoiceList,
  NoticeChoiceList,
  RetryChoiceList,
  ToolCallingChoiceList,
  WorkflowModeChoiceList,
} from "./AgentPolicyLists";

const codingNames = [
  "coding_local",
  "coding_cursor",
  "coding_codex",
  "python_data",
];
const isCoding = (tools: string[]) =>
  tools.some((name) => codingNames.includes(name));
const isExternalCoding = (tools: string[]) =>
  tools.some((name) => ["coding_cursor", "coding_codex"].includes(name));
const agentModelLabel = (agent: {
  tools: string[];
  model: string;
  media?: AgentMediaScope | null;
}) =>
  agent.tools.includes("market_watch")
    ? "Deterministic · no model or GPU"
    : fixedAgentMedia(agent)
      ? `Local ${agent.media?.kind ?? "media"} engine`
      : isExternalCoding(agent.tools)
        ? `${agent.tools[0] === "coding_codex" ? "Codex" : "Cursor"} · EXTERNAL · CLI default model`
        : isCoding(agent.tools) && agent.model === "auto"
          ? agent.tools.includes("python_data")
            ? "Auto · local data analysis"
            : "Auto Local Coding · 100k+ context"
          : agent.model || "No model selected";

type Trigger = "manual" | "interval" | "cron" | "datetime";
interface Agent {
  id: string;
  name: string;
  description: string;
  goal: string;
  system_prompt: string;
  model: string;
  tools: string[];
  market?: MarketScope | null;
  market_readiness?: { ready: boolean; reason: string | null } | null;
  market_email_authorization?: MarketEmailAuthorization | null;
  data?: DataScope | null;
  media?: AgentMediaScope | null;
  workspace_policy?: WorkspacePolicy;
  data_readiness?: { ready: boolean; reason: string } | null;
  permission_profile?: "agent_local" | "agent_external_coding";
  github?: { connector_id: string; repository: string } | null;
  search_query: string;
  fetch_urls: string[];
  skills: string[];
  trigger: Trigger;
  cron_expr: string;
  interval_seconds: number | null;
  run_at: string | null;
  maximum_runtime: number;
  output_expectation: string;
  require_approval: boolean;
  workflow_mode: "sequential" | "gated";
  tool_calling: "none" | "bounded";
  retry_policy: { mode: "none" | "manual" };
  notification_policy: {
    on_success: boolean;
    on_failure: boolean;
    on_approval: boolean;
  };
  project_id: string | null;
  enabled: boolean;
  updated_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  failure_count: number;
  effective_permissions: string[];
  runs?: Run[];
}
interface Tool {
  name: string;
  description: string;
  operational: boolean;
  required_permissions: string[];
  outputs?: Partial<
    Record<AgentMediaScope["kind"], { ready: boolean; reason?: string | null }>
  >;
}
interface Skill {
  id: string;
  name: string;
  version: string;
  description: string;
  required_permissions: string[];
  instructions: string;
}
const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const schedule = (agent: Agent) =>
  agent.trigger === "cron"
    ? `${agent.cron_expr} (UTC)`
    : agent.trigger === "interval"
      ? `Every ${agent.interval_seconds} seconds`
      : agent.trigger === "datetime"
        ? `Once: ${time(agent.run_at)}`
        : "Manual";

function toolTitle(tool: Tool) {
  if (tool.name === "create_media") return "Create media";
  if (tool.name === "search_pages") return "Read search sources";
  return tool.name === "github_read"
    ? "GitHub repository"
    : tool.name === "coding_cursor"
      ? "Cursor coding · EXTERNAL"
      : tool.name === "coding_codex"
        ? "Codex coding · EXTERNAL"
        : tool.name === "coding_local"
          ? "Local coding"
          : tool.name === "remember_report"
            ? "Remember reports"
            : tool.name === "remember_workflow"
              ? "Remember workflow observations"
              : tool.name === "http_fetch"
                ? "HTTP fetch"
                : tool.name === "project_memory"
                  ? "Project memory"
                  : tool.name === "browser"
                    ? "Browse public pages"
                    : tool.name;
}

function toggleValue(selected: string[], value: string, enabled: boolean) {
  if (enabled)
    return selected.includes(value) ? selected : [...selected, value];
  return selected.filter((item) => item !== value);
}

function SkillChoiceList({
  skills,
  selected,
  onChange,
}: {
  skills: Skill[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    skills,
    (skill) => skill.id,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const skill = skills[index];
    if (!skill) return;
    event.preventDefault();
    onChange(toggleValue(selected, skill.id, !selected.includes(skill.id)));
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a skill while the list is focused. Space or Enter
        selects it. Review instructions stays on the selected row. Skills do not
        grant tools. There is no inspectable Skill Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {skills.map((skill, i) => {
          const current = i === index;
          const checked = selected.includes(skill.id);
          return (
            <div
              key={skill.id}
              aria-label={`Skill ${skill.name} ${skill.id}`}
              {...itemProps(i, skill.id)}
            >
              <label className="agent-tool">
                <input
                  type="checkbox"
                  checked={checked}
                  tabIndex={current ? 0 : -1}
                  onChange={(event) =>
                    onChange(
                      toggleValue(selected, skill.id, event.target.checked),
                    )
                  }
                />
                <span>
                  <strong>{skill.name}</strong>{" "}
                  <small>
                    {skill.id} {skill.version}. {skill.description}{" "}
                    {skill.required_permissions.join(", ")}
                  </small>
                </span>
              </label>
              {checked && (
                <details className="agent-skill-text">
                  <summary>{`Review ${skill.name} ${skill.id} instructions`}</summary>
                  <pre>{skill.instructions}</pre>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function ToolChoiceList({
  tools,
  selected,
  onChange,
}: {
  tools: Tool[];
  selected: string[];
  onChange: (names: string[]) => void;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    tools,
    (tool) => tool.name,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const tool = tools[index];
    if (!tool) return;
    const checked = selected.includes(tool.name);
    if (!tool.operational && !checked) return;
    event.preventDefault();
    onChange(toggleValue(selected, tool.name, !checked));
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a tool while the list is focused. Space or Enter
        selects an operational tool. Unavailable tools stay visible and block
        activation. There is no inspectable tool-selection Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {tools.map((tool, i) => {
          const current = i === index;
          const checked = selected.includes(tool.name);
          return (
            <div
              key={tool.name}
              aria-label={`Tool ${tool.name}`}
              {...itemProps(i, tool.name)}
            >
              <label className="agent-tool">
                <input
                  type="checkbox"
                  checked={checked}
                  tabIndex={current ? 0 : -1}
                  disabled={!tool.operational && !checked}
                  onChange={(event) =>
                    onChange(
                      toggleValue(selected, tool.name, event.target.checked),
                    )
                  }
                />
                <span>
                  <strong>{toolTitle(tool)}</strong>{" "}
                  {!tool.operational && "— Unavailable"}
                  <small>
                    {tool.description} {tool.required_permissions.join(", ")}
                  </small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}

function AgentCards({
  agents,
  projects,
}: {
  agents: Agent[];
  projects: { id: string; name: string }[];
}) {
  const headingId = useId();
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
    if (target.closest("a, button, textarea, input, select")) return;
    if (selected?.id) {
      event.preventDefault();
      navigate(`/agents/${selected.id}`);
    }
  };
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        Agents
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an agent while the list is focused. Enter inspects it.
        Inspect project and View tagged Runs stay on a saved link. View tagged
        Runs stays on a saved agent even without a project. Linking does not
        grant coding, Git or repository access. This list does not Enable or Run
        now.
      </p>
      <div
        ref={listRef}
        className="memory-grid"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {agents.map((agent, i) => {
          const current = i === index;
          const shortId = agent.id.slice(0, 8);
          return (
            <article
              className="panel memory-card"
              key={agent.id}
              {...itemProps(i, agent.id)}
              onClick={(event) => {
                if (
                  (event.target as HTMLElement).closest(
                    "a, button, textarea, input, select",
                  )
                )
                  return;
                navigate(`/agents/${agent.id}`);
              }}
            >
              <div className="row">
                <span className="tiny-tag">
                  {isExternalCoding(agent.tools) ? "EXTERNAL" : "LOCAL"}
                </span>
                <span className="tiny-tag">
                  {agent.enabled ? "Enabled" : "Paused / draft"}
                </span>
              </div>
              <h2>
                <Link
                  className="text-link"
                  to={`/agents/${agent.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect ${agent.name} ${shortId}`}
                >
                  {agent.name}
                </Link>
              </h2>
              <p className="agent-goal">{agent.goal}</p>
              <p className="muted">
                {schedule(agent)} · {agentModelLabel(agent)}
              </p>
              <p>Last: {agent.last_status || "Never run"}</p>
              <small className="muted">Next: {time(agent.next_run_at)}</small>
              <AgentLinkedProjectLinks
                agentId={agent.id}
                projectId={agent.project_id}
                projectName={
                  projects.find((item) => item.id === agent.project_id)?.name
                }
                tabIndex={current ? 0 : -1}
              />
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function Agents() {
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const projectId = params.get("project_id") ?? "";
  const agents = useQuery({
    queryKey: ["agents", offset, projectId],
    queryFn: () =>
      api<Agent[]>(
        `/agents?limit=50&offset=${offset}${
          projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""
        }`,
      ),
    refetchInterval: 5000,
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ id: string; name: string }[]>("/projects?limit=500"),
  });
  return (
    <>
      <PageTitle eyebrow="AUTOMATION / AGENTS" title="Agents">
        Persistent instructions, explicit tools, and a history for every
        execution.
      </PageTitle>
      <AgentDraftForm />
      <div className="toolbar">
        <label>
          Filter linked project{" "}
          <select
            value={projectId}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              if (event.target.value)
                next.set("project_id", event.target.value);
              else next.delete("project_id");
              setParams(next, { replace: true });
              setOffset(0);
            }}
          >
            <option value="">All projects</option>
            {projectId &&
              !(projects.data ?? []).some((row) => row.id === projectId) && (
                <option value={projectId}>{projectId}</option>
              )}
            {(projects.data ?? []).map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorNotice error={agents.error ?? projects.error} />
      {agents.isPending ? (
        <Loading />
      ) : !agents.data?.length ? (
        <section className="panel">
          <Empty title="No agents in this view">
            {projectId
              ? "No agents are linked to this project. Linking tags Runs for filtering and does not grant coding, Git or repository access."
              : "Start with a draft, inspect its permissions and schedule, then enable it."}
          </Empty>
        </section>
      ) : (
        <AgentCards agents={agents.data} projects={projects.data ?? []} />
      )}
      <div className="row">
        <Button
          variant="secondary"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          disabled={agents.data?.length !== 50}
          onClick={() => setOffset(offset + 50)}
        >
          Next
        </Button>
      </div>
    </>
  );
}

export function AgentDetail() {
  const [emailConsent, setEmailConsent] = useState<string | null>(null);
  const [emailReady, setEmailReady] = useState(false);
  const { id } = useParams();
  const [viewParams, setViewParams] = useSearchParams();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const detail = useQuery({
    queryKey: ["agent", id],
    queryFn: () => api<Agent>(`/agents/${id}`),
    refetchInterval: 3000,
  });
  const action = useMutation({
    mutationFn: ({
      operation,
      enabled,
    }: {
      operation: string;
      enabled?: boolean;
    }) =>
      api<{ id: string }>(
        `/agents/${id}/${operation}`,
        json("POST", {
          expected_updated_at: detail.data!.updated_at,
          ...(enabled === undefined ? {} : { enabled }),
          ...(enabled && detail.data?.market?.email
            ? {
                confirm_market_email:
                  emailConsent ===
                  marketEmailConsentKey(detail.data.id, detail.data.market),
              }
            : {}),
        }),
      ),
    onSuccess: (result, variables) => {
      setEmailConsent(null);
      void cache.invalidateQueries({ queryKey: ["agent", id] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      if (variables.operation === "run") {
        setViewParams((current) => {
          const next = new URLSearchParams(current);
          next.set("view", "workspace");
          return next;
        });
      }
      if (variables.operation === "duplicate") navigate(`/agents/${result.id}`);
    },
  });
  const catalog = useQuery({
    queryKey: ["agent-tools"],
    queryFn: () => api<Tool[]>("/agents/tools"),
  });
  const skillsCatalog = useQuery({
    queryKey: ["skills"],
    queryFn: () => api<unknown>("/skills"),
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ id: string; name: string }[]>("/projects?limit=500"),
  });
  const modelCatalog = useQuery({
    queryKey: ["llama-models"],
    queryFn: () =>
      api<{ models: { id: string; name: string; model_key: string }[] }>(
        "/llama",
      ),
  });
  const agent = detail.data;
  if (!agent)
    return (
      <>
        <ErrorNotice error={detail.error} />
        {detail.isPending && <Loading />}
      </>
    );
  const view =
    viewParams.get("view") === "settings"
      ? "settings"
      : viewParams.get("view") === "workspace" ||
          agent.runs?.length ||
          agent.enabled
        ? "workspace"
        : "settings";
  const viewLink = (value: string) => {
    const next = new URLSearchParams(viewParams);
    next.set("view", value);
    return `?${next}`;
  };
  const taskId = agent.runs?.[0]?.task_id;
  const actualModel = agent.runs?.find(
    (run) =>
      run.task_id === taskId && typeof run.parameters?.model === "string",
  )?.parameters.model;
  const modelKey =
    agent.model === "auto" && typeof actualModel === "string"
      ? actualModel
      : agent.model;
  const selectedModel = modelCatalog.data?.models?.find(
    (model) =>
      model.model_key === modelKey || `llamacpp:${model.id}` === modelKey,
  );
  const modelLabel =
    selectedModel?.name ??
    (modelKey.startsWith("llamacpp:") ? "Local llama.cpp" : modelKey);
  const block = activationBlock(agent, catalog.data, skillsCatalog.data);
  const active = agent.runs?.some((run) => !terminal.has(run.status)) ?? false;
  const waiting = agent.runs?.find(
    (run) => run.status === "waiting_for_approval",
  );
  return (
    <>
      <PageTitle
        eyebrow={
          agent.tools.includes("market_watch")
            ? "Deterministic · no model or GPU"
            : isExternalCoding(agent.tools)
              ? "AGENT / EXTERNAL CODING"
              : "AGENT / LOCAL EXECUTION"
        }
        title={agent.name}
        action={
          <Link className="button secondary" to="/agents">
            All agents
          </Link>
        }
      >
        {agent.enabled ? "Enabled" : "Paused / draft"} · {schedule(agent)} ·{" "}
        {agent.model === "auto"
          ? `${agentModelLabel(agent)}${selectedModel ? ` · ${selectedModel.name}` : ""}`
          : agentModelLabel({ ...agent, model: modelLabel })}
        {agent.skills?.length ? ` · Skills: ${agent.skills.join(", ")}` : ""}
      </PageTitle>
      <nav className="agent-workspace-nav" aria-label="Agent workspace views">
        <Link
          to={viewLink("workspace")}
          aria-current={view === "workspace" ? "page" : undefined}
        >
          Workspace
        </Link>
        <Link
          to={viewLink("settings")}
          aria-current={view === "settings" ? "page" : undefined}
        >
          Settings
        </Link>
      </nav>
      <section
        className="panel agent-form agent-workspace-summary"
        aria-label="Agent status and actions"
      >
        <p className="agent-workspace-goal">{agent.goal}</p>
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
            disabled={
              action.isPending ||
              block.blocked ||
              (!agent.enabled &&
                !!agent.market?.email &&
                (!emailReady ||
                  emailConsent !==
                    marketEmailConsentKey(agent.id, agent.market)))
            }
            onClick={() =>
              action.mutate({ operation: "enabled", enabled: !agent.enabled })
            }
          >
            {agent.enabled
              ? "Pause agent"
              : agent.market?.email
                ? "Enable and allow alert email"
                : "Enable saved definition"}
          </Button>
          <Button
            variant="secondary"
            disabled={
              action.isPending ||
              !agent.enabled ||
              active ||
              (!!agent.market?.email &&
                !agent.market_email_authorization?.valid)
            }
            onClick={() => action.mutate({ operation: "run" })}
          >
            Run now
          </Button>
          {(agent.tools.includes("market_watch") ||
            agent.tools.includes("create_media")) && (
            <AgentMarketRunStop
              agentId={agent.id}
              runs={agent.runs ?? []}
              subject={
                agent.tools.includes("create_media")
                  ? "media generation"
                  : "price check"
              }
            />
          )}
          <Button
            variant="ghost"
            disabled={action.isPending}
            onClick={() => action.mutate({ operation: "duplicate" })}
          >
            Duplicate as draft
          </Button>
        </div>
        <p className="muted">
          {agent.enabled
            ? `Next run: ${time(agent.next_run_at)}`
            : "Paused · enable the saved definition to run this agent."}
          {agent.last_run_at
            ? ` · Last run: ${time(agent.last_run_at)} · ${agent.last_status}`
            : " · No executions yet"}
        </p>
        {waiting ? (
          <div className="agent-approval">
            <p className="notice">
              A Run is waiting for approval. Granting queues it for the worker;
              tools and inference have not started. Deny cancels it. That does
              not call Run now.
            </p>
            <div className="row">
              <RunApprovalActions runId={waiting.id} name="waiting Run" />
              <Button asChild variant="secondary">
                <Link
                  to={`/runs/${waiting.id}`}
                  aria-label={`Review waiting Run ${waiting.id.slice(0, 8)}`}
                >
                  Review it
                </Link>
              </Button>
            </div>
          </div>
        ) : null}
        <ErrorNotice error={action.error ?? detail.error ?? projects.error} />
      </section>
      <div hidden={view !== "workspace"} className="agent-workspace-body">
        {agent.runs?.length ? (
          <>
            {agent.tools.includes("create_media") && (
              <AgentMediaResult runs={agent.runs ?? []} />
            )}
            {agent.tools.includes("python_data") && (
              <AgentDataResult runs={agent.runs ?? []} />
            )}
            {(agent.market ||
              agent.runs.some((run) => run.executor_type === "email_send")) && (
              <AgentMarketEmailHistory agentId={agent.id} runs={agent.runs} />
            )}
            {!isCoding(agent.tools) && <AgentLatestReport runs={agent.runs} />}
            {isCoding(agent.tools) && !agent.tools.includes("python_data") && (
              <AgentCodeWorkspace runs={agent.runs} />
            )}
            <AgentLastWorkflowSteps runs={agent.runs} />
            <AgentExecutionHistory runs={agent.runs} />
          </>
        ) : (
          <section className="panel agent-form">
            <h2>Execution history</h2>
            <p className="muted">
              Your agent's results, files and progress will appear here.
            </p>
            <p className="muted">
              Review its instructions and tools in Settings, then enable the
              saved definition and choose Run now.
            </p>
            <Link to={viewLink("settings")} className="text-link">
              Review agent settings
            </Link>
          </section>
        )}
      </div>
      <div hidden={view !== "settings"} className="agent-workspace-body">
        <p className="muted agent-workspace-settings-note">
          Save changes before enabling or running. Pausing stops future
          schedules; use Stop in the workspace to cancel an execution already in
          progress.
        </p>
        <AgentEditor key={agent.id} agent={agent} active={active} />
        <section
          className="panel agent-form"
          aria-label="Permissions and related resources"
        >
          <div className="agent-fields">
            <div>Next run: {time(agent.next_run_at)}</div>
            <div>Last run: {time(agent.last_run_at)}</div>
            <div>Last status: {agent.last_status || "Never run"}</div>
            <div>Consecutive failures: {agent.failure_count}</div>
          </div>
          <p>
            Effective permissions:{" "}
            {agent.effective_permissions.join(", ") ||
              "No host or external tools"}
          </p>
          <Link to={`/memory?scope=agent&scope_id=${agent.id}`}>
            Inspect this agent's memory
          </Link>
          <AgentLinkedProjectLinks
            agentId={agent.id}
            projectId={agent.project_id}
            projectName={
              projects.data?.find((item) => item.id === agent.project_id)?.name
            }
          />
          {agent.project_id ? (
            <ProjectAgents
              projectId={agent.project_id}
              excludeAgentId={agent.id}
            />
          ) : null}
        </section>
      </div>
    </>
  );
}

const fetchLines = (urls: string[] | undefined) => (urls ?? []).join("\n");
const parseFetchUrls = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

function AgentEditor({ agent, active }: { agent: Agent; active: boolean }) {
  const cache = useQueryClient();
  const [values, setValues] = useState(agent);
  const [fetchText, setFetchText] = useState(fetchLines(agent.fetch_urls));
  const [serverVersion, setServerVersion] = useState(agent.updated_at);
  const [dirty, setDirty] = useState(false);
  if (serverVersion !== agent.updated_at) {
    setServerVersion(agent.updated_at);
    if (!dirty) {
      setValues(agent);
      setFetchText(fetchLines(agent.fetch_urls));
    }
  }
  const editValues = (next: Agent | ((current: Agent) => Agent)) => {
    setDirty(true);
    setValues(next);
  };
  const [modelBusy, setModelBusy] = useState(false);
  const [mediaBusy, setMediaBusy] = useState(false);
  const mediaScope = values.tools.includes("create_media")
    ? (values.media ?? newAgentMedia("image", values.goal))
    : null;
  const mediaIssue = values.tools.includes("create_media")
    ? agentMediaIssue(mediaScope, {
        allowMissingVoice: !agent.enabled,
        allowMissingSources: !agent.enabled,
      })
    : null;
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
  });
  const tools = useQuery({
    queryKey: ["agent-tools"],
    queryFn: () => api<Tool[]>("/agents/tools"),
  });
  const skills = useQuery({
    queryKey: ["skills"],
    queryFn: () => api<Skill[]>("/skills"),
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ id: string; name: string }[]>("/projects?limit=500"),
  });
  const update = <K extends keyof Agent>(key: K, value: Agent[K]) =>
    editValues((current) => ({ ...current, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      api<Agent>(
        `/agents/${agent.id}`,
        json(
          "PUT",
          agentSettingsPayload(agent, {
            ...values,
            fetch_urls: parseFetchUrls(fetchText),
            ...(values.tools.includes("create_media")
              ? { media: mediaScope }
              : {}),
            enabled: agent.enabled,
          }),
        ),
      ),
    onSuccess: (result) => {
      setDirty(false);
      setValues(result);
      setFetchText(fetchLines(result.fetch_urls));
      void cache.invalidateQueries({ queryKey: ["agent", agent.id] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
    },
  });
  const stale = values.updated_at !== agent.updated_at;
  return (
    <form
      className="panel agent-form"
      onChangeCapture={() => {
        setDirty(true);
        if (save.isSuccess) save.reset();
      }}
      onClickCapture={() => {
        if (save.isSuccess) save.reset();
      }}
      onSubmit={(event) => {
        event.preventDefault();
        if (!modelBusy && !mediaBusy && !mediaIssue && !active && !stale)
          save.mutate();
      }}
    >
      <h2>Definition</h2>
      {stale && (
        <div className="notice">
          The saved definition changed. Your edits are preserved.{" "}
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setDirty(false);
              setValues(agent);
              setFetchText(fetchLines(agent.fetch_urls));
            }}
          >
            Reload saved definition
          </Button>
        </div>
      )}
      {active && (
        <p className="muted">Finish or cancel the active Run before editing.</p>
      )}
      <fieldset
        disabled={active || save.isPending || mediaBusy}
        className="agent-fields"
      >
        <label>
          Name
          <input
            required
            maxLength={200}
            value={values.name}
            onChange={(e) => update("name", e.target.value)}
          />
        </label>
        {values.tools.includes("market_watch") ? (
          <p className="muted">
            Deterministic price watch · no model or GPU needed.
          </p>
        ) : fixedAgentMedia({ ...values, media: mediaScope }) ? (
          <p className="muted">
            Local media engine · uses your exact saved description.
          </p>
        ) : isExternalCoding(values.tools) ? (
          <p className="notice">
            EXTERNAL coding uses the selected CLI's default model and existing
            login. Your goal, guidance and relevant project files are shared
            with {values.tools[0] === "coding_codex" ? "Codex" : "Cursor"}.
            Enable only after reviewing this project scope.
          </p>
        ) : (
          <>
            {isCoding(values.tools) && (
              <label>
                Coding model policy
                <select
                  aria-label="Coding model policy"
                  disabled={modelBusy || active || save.isPending}
                  value={values.model === "auto" ? "auto" : "explicit"}
                  onChange={(event) =>
                    update("model", event.target.value === "auto" ? "auto" : "")
                  }
                >
                  <option value="auto">
                    Auto · fitting local model with 100k+ context
                  </option>
                  <option value="explicit">
                    Choose a specific local model
                  </option>
                </select>
              </label>
            )}
            {(!isCoding(values.tools) || values.model !== "auto") && (
              <LlamaModels
                value={values.model}
                models={provider.data?.models ?? []}
                onSelect={(model) => update("model", model)}
                onBusy={setModelBusy}
                busy={active || save.isPending}
              />
            )}
          </>
        )}
        <label className="agent-wide">
          Description
          <input
            maxLength={4000}
            value={values.description}
            onChange={(e) => update("description", e.target.value)}
          />
        </label>
        <div className="agent-wide">
          <h3>
            {values.tools.includes("coding_local") ||
            values.tools.includes("python_data")
              ? "Workspace"
              : "Linked project"}
          </h3>
          <AgentProjectList
            automaticWorkspace={
              values.tools.includes("coding_local") ||
              values.tools.includes("python_data")
            }
            agentId={agent.id}
            projectId={values.project_id ?? null}
            projects={projects.data ?? []}
            disabled={active || save.isPending}
            onSave={(project_id) => update("project_id", project_id)}
          />
        </div>
        {values.tools.includes("market_watch") && (
          <AgentMarketScope
            value={values.market}
            disabled={active || save.isPending}
            onChange={(market) => update("market", market)}
          />
        )}
        {values.tools.includes("coding_local") && (
          <AgentWorkspacePolicy
            value={values.workspace_policy}
            linkedProject={values.project_id}
            disabled={active || save.isPending}
            onChange={(value) => update("workspace_policy", value)}
          />
        )}
        <label className="agent-wide">
          Goal
          <textarea
            required
            maxLength={isCoding(values.tools) ? 10000 : 16000}
            rows={3}
            value={values.goal}
            onChange={(e) => update("goal", e.target.value)}
          />
        </label>
        {values.tools.includes("create_media") && (
          <div className="agent-wide">
            <AgentMediaScopeEditor
              value={mediaScope}
              goal={values.goal}
              disabled={active || save.isPending}
              readiness={
                tools.data?.find((tool) => tool.name === "create_media")
                  ?.outputs
              }
              onBusy={setMediaBusy}
              onChange={(media) =>
                editValues((current) => ({
                  ...current,
                  media,
                  ...(media.description_source === "fixed"
                    ? {
                        tools: ["create_media"],
                        skills: [],
                        tool_calling: "none" as const,
                      }
                    : {}),
                }))
              }
            />
          </div>
        )}
        <label className="agent-wide">
          System prompt
          <textarea
            maxLength={8000}
            rows={3}
            value={values.system_prompt}
            onChange={(e) => update("system_prompt", e.target.value)}
          />
        </label>
        <label>
          Trigger
          <select
            value={values.trigger}
            onChange={(e) => update("trigger", e.target.value as Trigger)}
          >
            <option value="manual">Manual</option>
            <option value="interval">Interval</option>
            <option value="cron">Cron (UTC)</option>
            <option value="datetime">One-shot (UTC)</option>
          </select>
        </label>
        {values.trigger === "interval" && (
          <label>
            Interval seconds
            <input
              type="number"
              required
              min={60}
              max={31536000}
              value={values.interval_seconds ?? 3600}
              onChange={(e) =>
                update("interval_seconds", Number(e.target.value))
              }
            />
          </label>
        )}
        {values.trigger === "cron" && (
          <label>
            Cron expression (UTC)
            <input
              required
              value={values.cron_expr}
              placeholder="0 8 * * *"
              onChange={(e) => update("cron_expr", e.target.value)}
            />
          </label>
        )}
        {values.trigger === "datetime" && (
          <label>
            One-shot time (UTC)
            <input
              required
              type="datetime-local"
              value={values.run_at?.slice(0, 16) ?? ""}
              onChange={(e) =>
                update(
                  "run_at",
                  e.target.value ? `${e.target.value}:00Z` : null,
                )
              }
            />
          </label>
        )}
        <label>
          Maximum runtime (seconds)
          <input
            type="number"
            required
            min={5}
            max={3600}
            value={values.maximum_runtime}
            onChange={(e) => update("maximum_runtime", Number(e.target.value))}
          />
        </label>
        {!isCoding(values.tools) && !values.tools.includes("create_media") && (
          <label className="agent-wide">
            Expected output
            <textarea
              maxLength={4000}
              rows={2}
              value={values.output_expectation}
              onChange={(e) => update("output_expectation", e.target.value)}
            />
          </label>
        )}
        <div className="agent-wide">
          <ApprovalChoiceList
            checked={values.require_approval ?? false}
            onChange={(value) => update("require_approval", value)}
          />
        </div>
        <fieldset className="agent-wide">
          <legend>Workflow steps</legend>
          <p className="muted">
            {values.tools.includes("create_media") ? (
              "Research finishes before creative preparation and generation. Stop cancels the whole execution. Your saved output settings stay fixed."
            ) : (
              <>
                Selected context tools become persisted child Runs with
                dependencies. The model cannot add tools, URLs or shell
                commands. Cancel stops the currently active child. Remember
                reports still runs only after a successful report. Bounded tool
                calling is extra registry calls during the report, not a shell
                or browser.
              </>
            )}
          </p>
          {!isCoding(values.tools) &&
            !values.tools.includes("market_watch") &&
            !values.tools.includes("create_media") && (
              <ToolCallingChoiceList
                mode={values.tool_calling ?? "none"}
                onChange={(mode) => update("tool_calling", mode)}
              />
            )}
          {!values.tools.includes("market_watch") && (
            <WorkflowModeChoiceList
              output={
                values.tools.includes("create_media") ? "media" : "report"
              }
              mode={values.workflow_mode ?? "sequential"}
              onChange={(mode) => update("workflow_mode", mode)}
            />
          )}
        </fieldset>
        <fieldset className="agent-wide">
          <legend>Retry</legend>
          <p className="muted">
            Failed workflows are never retried automatically. Manual retry
            starts a new inspectable Run from the same snapshot. It does not
            resume or replay a search, fetch or inference that already had an
            uncertain outcome.
          </p>
          <RetryChoiceList
            mode={values.retry_policy?.mode ?? "none"}
            onChange={(mode) => update("retry_policy", { mode })}
          />
        </fieldset>
        <fieldset className="agent-wide">
          <legend>Notifications</legend>
          <p className="muted">
            Notices stay in AI Station. Email, chat and other connectors are not
            enabled. Existing agents stay silent until you opt in.
          </p>
          <NoticeChoiceList
            output={values.tools.includes("create_media") ? "media" : "report"}
            policy={{
              on_success: Boolean(values.notification_policy?.on_success),
              on_failure: Boolean(values.notification_policy?.on_failure),
              on_approval: Boolean(values.notification_policy?.on_approval),
            }}
            onChange={(policy) => update("notification_policy", policy)}
          />
        </fieldset>
        {values.tools.includes("web_search") && (
          <section className="agent-wide agent-search-settings">
            <h3>Internet research</h3>
            <label>
              Public search query
              <input
                required
                maxLength={500}
                value={values.search_query ?? ""}
                onChange={(e) => update("search_query", e.target.value)}
                placeholder="e.g. new open-weight language models GPU benchmarks"
              />
            </label>
            <p className="muted">
              This exact query is sent to search engines on each execution. Your
              goal, memory and other context stay with the local model. Review
              it before enabling the agent.
            </p>
            <span className="chip">Network permission · search only</span>
          </section>
        )}
        {values.tools.includes("github_read") && (
          <section className="agent-wide agent-search-settings">
            <h3>GitHub repository</h3>
            <GithubAgentScope
              value={values.github ?? null}
              disabled={active || save.isPending}
              onChange={(github) => update("github", github)}
            />
          </section>
        )}
        {(values.tools.includes("http_fetch") ||
          values.tools.includes("browser")) && (
          <section className="agent-wide agent-search-settings">
            <h3>Public pages</h3>
            <label>
              {values.tools.includes("browser")
                ? "Public URLs to browse"
                : "Public URLs to fetch"}
              <textarea
                required
                rows={3}
                value={fetchText}
                onChange={(e) => setFetchText(e.target.value)}
                placeholder="https://www.example.com/"
              />
            </label>
            {values.tools.includes("browser") ? (
              <p className="muted">
                Opens these reviewed public pages in an isolated browser,
                executes JavaScript and saves screenshots and visible text. At
                most three URLs; private addresses and writes are blocked. Your
                goal and memory stay with the local model.
              </p>
            ) : (
              <p className="muted">
                Each execution GETs these exact public http(s) pages (at most
                three). Private, loopback and link-local addresses are blocked
                after DNS. JavaScript is not executed. Your goal, memory and
                other context stay with the local model.
              </p>
            )}
            <span className="chip">
              {values.tools.includes("browser")
                ? "Browser + public network permission"
                : "Network permission · GET public pages"}
            </span>
          </section>
        )}
        {values.tools.includes("remember_report") && (
          <p className="notice agent-wide">
            Successful reports will be stored in this agent’s memory with their
            source Run. They are observations, not verified facts. Select
            memory_search to use them on future runs. You can edit, disable or
            delete them in Memory.
          </p>
        )}
        {values.tools.includes("remember_workflow") && (
          <p className="notice agent-wide">
            Successful telemetry, public search and HTTP fetch steps will be
            stored in this agent’s memory with their source Run. memory_search
            results are not copied. Failures and cancellation write nothing.
            Select memory_search to use them on future runs.
          </p>
        )}
        <div className="agent-wide">
          <h3>Skills</h3>
          <p className="muted">
            Versioned instruction packs from the skills directory. They do not
            grant tools, permissions or shell access. At most four. Review the
            text before enabling the agent.
          </p>
          {!skills.data?.length && (
            <p className="muted">
              No skills are installed. Add a SKILL.md under the configured
              skills directory to make one selectable.
            </p>
          )}
          {!!skills.data?.length && (
            <SkillChoiceList
              skills={skills.data}
              selected={values.skills ?? []}
              onChange={(ids) => update("skills", ids)}
            />
          )}
        </div>
        {values.tools.includes("python_data") && (
          <div className="agent-wide">
            <AgentDataFiles
              value={values.data}
              disabled={active || save.isPending}
              onChange={(data) => update("data", data)}
            />
          </div>
        )}
        <div className="agent-wide">
          <h3>Tools</h3>
          {isCoding(values.tools) && (
            <p className="notice">
              {isExternalCoding(values.tools)
                ? "External coding uses the goal as its task and the selected CLI."
                : "Local coding uses the goal as its task and the selected local model."}{" "}
              Each execution has an isolated branch, diff and validation
              results. Gated mode asks before starting. No automatic commit or
              publication.
            </p>
          )}
          <p className="muted">
            Context tools become inspectable workflow steps before the report.
            Remember reports and remember workflow observations run after those
            successful steps. Unavailable tools prevent activation.
          </p>
          {!!tools.data?.length && (
            <ToolChoiceList
              tools={
                mediaScope?.kind === "image" &&
                mediaScope.request.mode === "upscale"
                  ? tools.data.filter((tool) => tool.name === "create_media")
                  : values.tools.includes("create_media")
                    ? tools.data.filter(
                        (tool) => tool.name !== "remember_report",
                      )
                    : tools.data
              }
              selected={values.tools}
              onChange={(names) => {
                const addedCoding = names.find(
                  (name) =>
                    codingNames.includes(name) && !values.tools.includes(name),
                );
                const addedMarket =
                  names.includes("market_watch") &&
                  !values.tools.includes("market_watch");
                let selected = addedMarket
                  ? ["market_watch"]
                  : addedCoding
                    ? [
                        addedCoding,
                        ...(addedCoding === "coding_local" &&
                        names.includes("http_fetch")
                          ? ["http_fetch"]
                          : []),
                      ]
                    : names.length === 1 && codingNames.includes(names[0])
                      ? names
                      : names.includes("coding_local") &&
                          names.every((name) =>
                            ["coding_local", "http_fetch"].includes(name),
                          )
                        ? names
                        : names.filter(
                            (name) =>
                              !codingNames.includes(name) &&
                              (names.length === 1 || name !== "market_watch"),
                          );
                if (selected.includes("create_media"))
                  selected = selected.filter(
                    (name) => name !== "remember_report",
                  );
                editValues((current) => ({
                  ...current,
                  tools: selected,
                  market: selected.includes("market_watch")
                    ? (current.market ?? DEFAULT_MARKET)
                    : null,
                  ...(addedMarket
                    ? {
                        model: "",
                        skills: [],
                        tool_calling: "none" as const,
                        workflow_mode: "sequential" as const,
                      }
                    : {}),
                  data: selected.includes("python_data") ? current.data : null,
                  ...(selected.includes("create_media")
                    ? { tool_calling: "none" as const }
                    : {}),
                  media: selected.includes("create_media")
                    ? {
                        ...(current.media ??
                          newAgentMedia("image", current.goal)),
                        description_source:
                          selected.length > 1
                            ? "goal"
                            : (current.media?.description_source ?? "goal"),
                      }
                    : null,
                  permission_profile: isExternalCoding(selected)
                    ? "agent_external_coding"
                    : "agent_local",
                  ...(addedCoding
                    ? {
                        model: isExternalCoding(selected) ? "" : "auto",
                        tool_calling: "none" as const,
                        require_approval:
                          isExternalCoding(selected) ||
                          current.require_approval,
                      }
                    : {}),
                }));
              }}
            />
          )}
        </div>
      </fieldset>
      <ErrorNotice
        error={save.error ?? tools.error ?? skills.error ?? projects.error}
      />
      <div>
        <Button
          disabled={
            active ||
            stale ||
            modelBusy ||
            mediaBusy ||
            !!mediaIssue ||
            save.isPending
          }
        >
          Save definition
        </Button>
        {save.isSuccess && (
          <p role="status" className="muted">
            Definition saved.
          </p>
        )}
      </div>
    </form>
  );
}
