import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Run } from "../api";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import LlamaModels from "./LlamaModels";
import { time } from "../lib/utils";

type Trigger = "manual" | "interval" | "cron" | "datetime";
interface Agent {
  id: string;
  name: string;
  description: string;
  goal: string;
  system_prompt: string;
  model: string;
  tools: string[];
  search_query: string;
  fetch_urls: string[];
  trigger: Trigger;
  cron_expr: string;
  interval_seconds: number | null;
  run_at: string | null;
  maximum_runtime: number;
  output_expectation: string;
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

export function Agents() {
  const navigate = useNavigate();
  const [instruction, setInstruction] = useState("");
  const [model, setModel] = useState("");
  const [modelBusy, setModelBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  const agents = useQuery({
    queryKey: ["agents", offset],
    queryFn: () => api<Agent[]>(`/agents?limit=50&offset=${offset}`),
    refetchInterval: 5000,
  });
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
  });
  const draft = useMutation({
    mutationFn: () =>
      api<Agent>(
        "/agents/draft",
        json("POST", {
          instruction,
          model: model || provider.data?.default_model || "",
        }),
      ),
    onSuccess: (agent) => navigate(`/agents/${agent.id}`),
  });
  return (
    <>
      <PageTitle eyebrow="AUTOMATION / LOCAL AGENTS" title="Agents">
        Persistent instructions, explicit tools, and a history for every
        execution.
      </PageTitle>
      <form
        className="panel agent-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!modelBusy) draft.mutate();
        }}
      >
        <h2>Create an agent draft</h2>
        <p className="muted">
          Describe the task and cadence. A deterministic parser proposes a
          disabled definition for your review. Creating a draft does not call a
          model.
        </p>
        <label>
          Instruction
          <textarea
            required
            maxLength={16000}
            rows={3}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="Every morning summarize my workstation's GPU and memory usage."
          />
        </label>
        <LlamaModels
          value={model || provider.data?.default_model || ""}
          models={provider.data?.models ?? []}
          onSelect={setModel}
          onBusy={setModelBusy}
          busy={draft.isPending}
        />
        <ErrorNotice error={draft.error} />
        <div>
          <Button
            disabled={draft.isPending || modelBusy || !instruction.trim()}
          >
            Create draft
          </Button>
        </div>
      </form>
      <ErrorNotice error={agents.error} />
      {agents.isPending ? (
        <Loading />
      ) : !agents.data?.length ? (
        <section className="panel">
          <Empty title="No agents in this view">
            Start with a draft, inspect its permissions and schedule, then
            enable it.
          </Empty>
        </section>
      ) : (
        <div className="memory-grid">
          {agents.data.map((agent) => (
            <Link
              className="panel memory-card"
              to={`/agents/${agent.id}`}
              key={agent.id}
            >
              <div className="row">
                <span className="tiny-tag">LOCAL</span>
                <span className="tiny-tag">
                  {agent.enabled ? "Enabled" : "Paused / draft"}
                </span>
              </div>
              <h2>{agent.name}</h2>
              <p className="agent-goal">{agent.goal}</p>
              <p className="muted">
                {schedule(agent)} · {agent.model || "No model selected"}
              </p>
              <p>Last: {agent.last_status || "Never run"}</p>
              <small className="muted">Next: {time(agent.next_run_at)}</small>
            </Link>
          ))}
        </div>
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
  const { id } = useParams();
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
        }),
      ),
    onSuccess: (result, variables) => {
      void cache.invalidateQueries({ queryKey: ["agent", id] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      if (variables.operation === "run") navigate(`/runs/${result.id}`);
      if (variables.operation === "duplicate") navigate(`/agents/${result.id}`);
    },
  });
  const agent = detail.data;
  if (!agent)
    return (
      <>
        <ErrorNotice error={detail.error} />
        {detail.isPending && <Loading />}
      </>
    );
  const active = agent.runs?.some((run) => !terminal.has(run.status)) ?? false;
  return (
    <>
      <PageTitle
        eyebrow="AGENT / LOCAL EXECUTION"
        title={agent.name}
        action={
          <Link className="button secondary" to="/agents">
            All agents
          </Link>
        }
      >
        {agent.enabled ? "Enabled" : "Paused / draft"} · {schedule(agent)} ·{" "}
        {agent.model || "No model selected"}
      </PageTitle>
      <section className="panel agent-form">
        <div className="row">
          <Button
            disabled={action.isPending}
            onClick={() =>
              action.mutate({ operation: "enabled", enabled: !agent.enabled })
            }
          >
            {agent.enabled ? "Pause agent" : "Enable saved definition"}
          </Button>
          <Button
            variant="secondary"
            disabled={action.isPending || !agent.enabled || active}
            onClick={() => action.mutate({ operation: "run" })}
          >
            Run now
          </Button>
          <Button
            variant="ghost"
            disabled={action.isPending}
            onClick={() => action.mutate({ operation: "duplicate" })}
          >
            Duplicate as draft
          </Button>
        </div>
        <p className="muted">
          Activation uses the saved definition. Pausing stops future scheduling;
          cancel an active execution from its Run page.
        </p>
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
        <ErrorNotice error={action.error ?? detail.error} />
      </section>
      <AgentEditor key={agent.id} agent={agent} active={active} />
      <section className="panel agent-form">
        <h2>Execution history</h2>
        {!agent.runs?.length ? (
          <p className="muted">No executions yet.</p>
        ) : (
          agent.runs.map((run) => (
            <Link className="row" key={run.id} to={`/runs/${run.id}`}>
              <Badge status={run.status} />
              <span>{time(run.created_at)}</span>
              <span className="mono">{run.id.slice(0, 8)}</span>
            </Link>
          ))
        )}
        <p className="muted">
          Latest 100 Runs. Open a Run to inspect events, parameters, errors, and
          report artifacts.
        </p>
      </section>
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
  const [modelBusy, setModelBusy] = useState(false);
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
  });
  const tools = useQuery({
    queryKey: ["agent-tools"],
    queryFn: () => api<Tool[]>("/agents/tools"),
  });
  const update = <K extends keyof Agent>(key: K, value: Agent[K]) =>
    setValues((current) => ({ ...current, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      api<Agent>(
        `/agents/${agent.id}`,
        json("PUT", {
          expected_updated_at: values.updated_at,
          name: values.name,
          description: values.description,
          goal: values.goal,
          system_prompt: values.system_prompt,
          model: values.model,
          tools: values.tools,
          search_query: values.search_query ?? "",
          fetch_urls: parseFetchUrls(fetchText),
          trigger: values.trigger,
          cron_expr: values.trigger === "cron" ? values.cron_expr : "",
          interval_seconds:
            values.trigger === "interval"
              ? (values.interval_seconds ?? 3600)
              : null,
          run_at: values.trigger === "datetime" ? values.run_at : null,
          maximum_runtime: values.maximum_runtime,
          output_expectation: values.output_expectation,
          project_id: values.project_id,
          enabled: agent.enabled,
        }),
      ),
    onSuccess: (result) => {
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
      onSubmit={(event) => {
        event.preventDefault();
        if (!modelBusy && !active && !stale) save.mutate();
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
      <fieldset disabled={active || save.isPending} className="agent-fields">
        <label>
          Name
          <input
            required
            maxLength={200}
            value={values.name}
            onChange={(e) => update("name", e.target.value)}
          />
        </label>
        <LlamaModels
          value={values.model}
          models={provider.data?.models ?? []}
          onSelect={(model) => update("model", model)}
          onBusy={setModelBusy}
          busy={active || save.isPending}
        />
        <label className="agent-wide">
          Description
          <input
            maxLength={4000}
            value={values.description}
            onChange={(e) => update("description", e.target.value)}
          />
        </label>
        <label className="agent-wide">
          Goal
          <textarea
            required
            maxLength={16000}
            rows={3}
            value={values.goal}
            onChange={(e) => update("goal", e.target.value)}
          />
        </label>
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
        <label className="agent-wide">
          Expected output
          <textarea
            maxLength={4000}
            rows={2}
            value={values.output_expectation}
            onChange={(e) => update("output_expectation", e.target.value)}
          />
        </label>
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
        {values.tools.includes("http_fetch") && (
          <section className="agent-wide agent-search-settings">
            <h3>Public pages</h3>
            <label>
              Public URLs to fetch
              <textarea
                required
                rows={3}
                value={fetchText}
                onChange={(e) => setFetchText(e.target.value)}
                placeholder="https://www.example.com/"
              />
            </label>
            <p className="muted">
              Each execution GETs these exact public http(s) pages (at most
              three). Private, loopback and link-local addresses are blocked
              after DNS. JavaScript is not executed. Your goal, memory and
              other context stay with the local model.
            </p>
            <span className="chip">Network permission · GET public pages</span>
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
        <div className="agent-wide">
          <h3>Tools</h3>
          <p className="muted">
            Context tools run before inference; Remember reports runs after a
            successful report. Unavailable tools prevent activation.
          </p>
          {tools.data?.map((tool) => (
            <label className="agent-tool" key={tool.name}>
              <input
                type="checkbox"
                checked={values.tools.includes(tool.name)}
                disabled={
                  !tool.operational && !values.tools.includes(tool.name)
                }
                onChange={(e) =>
                  update(
                    "tools",
                    e.target.checked
                      ? [...values.tools, tool.name]
                      : values.tools.filter((name) => name !== tool.name),
                  )
                }
              />
              <span>
                <strong>
                  {tool.name === "remember_report"
                    ? "Remember reports"
                    : tool.name === "http_fetch"
                      ? "HTTP fetch"
                      : tool.name}
                </strong>{" "}
                {!tool.operational && "— Unavailable"}
                <small>
                  {tool.description} {tool.required_permissions.join(", ")}
                </small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <ErrorNotice error={save.error ?? tools.error} />
      <div>
        <Button disabled={active || stale || modelBusy || save.isPending}>
          Save definition
        </Button>
      </div>
    </form>
  );
}
