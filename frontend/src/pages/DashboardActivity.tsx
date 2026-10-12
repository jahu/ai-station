import { useId, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

interface AgentSummary {
  id: string;
  name: string;
  model: string;
  trigger: string;
  next_run_at: string | null;
  last_status: string;
  overdue?: boolean;
  project_id?: string | null;
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
    agent_id?: string | null;
    project_id?: string | null;
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
    project_id?: string | null;
    run_id: string;
    kind: string;
    title: string;
    created_at: string;
    retry?: { allowed?: boolean; run_id?: string | null };
  }[];
  interrupted_runs?: {
    id: string;
    title: string;
    status: string;
    executor_type: string;
    replay?: boolean;
    agent_id?: string | null;
    project_id?: string | null;
  }[];
}

const CANCELABLE = new Set(["queued", "claimed", "preparing", "running"]);

type AttentionItem = {
  key: string;
  to: string;
  title: string;
  detail: string;
  status?: string;
  action?: "acknowledge" | "stop" | "stopping" | "read" | "approve";
  runId?: string;
  noticeId?: string;
  agentId?: string;
  projectId?: string | null;
  executorType?: string;
  retryWorkflowId?: string;
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
  inspectProps,
  current,
}: {
  to: string;
  title: string;
  detail: string;
  status?: string;
  thumbnail?: boolean;
  fallback?: ReactNode;
  action?: ReactNode;
  inspectLabel: string;
  inspectProps?: {
    "aria-current"?: "true";
    tabIndex: number;
    "data-list-index": number;
    onFocus: () => void;
  };
  current?: boolean;
}) {
  const id = to.split("/").pop() ?? title;
  return (
    <li className="activity-row" aria-current={current ? "true" : undefined}>
      <Link to={to} aria-label={inspectLabel} {...inspectProps}>
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

function taggedAgentLinks(
  agentId: string | undefined,
  projectId: string | null | undefined,
  current: boolean,
  includeAgent = false,
) {
  if (!agentId && !projectId) return null;
  const tab = current ? 0 : -1;
  const shortId = agentId?.slice(0, 8);
  const taggedTo = agentId
    ? projectId
      ? `/runs?project_id=${projectId}&agent_id=${agentId}`
      : `/runs?agent_id=${agentId}`
    : `/runs?project_id=${projectId}`;
  return (
    <>
      {includeAgent && agentId ? (
        <Link
          className="text-link"
          to={`/agents/${agentId}`}
          tabIndex={tab}
          aria-label={`Inspect agent ${shortId}`}
        >
          Inspect agent
        </Link>
      ) : null}
      {projectId ? (
        <Link
          className="text-link"
          to={`/projects/${projectId}`}
          tabIndex={tab}
          aria-label={`Inspect project ${projectId}`}
        >
          Inspect project
        </Link>
      ) : null}
      <Link
        className="text-link"
        to={taggedTo}
        tabIndex={tab}
        aria-label={`View tagged Runs ${shortId ?? projectId}`}
      >
        View tagged Runs
      </Link>
    </>
  );
}

function linkedProjectAction(agent: AgentSummary, current: boolean) {
  return taggedAgentLinks(agent.id, agent.project_id, current);
}

function KeyboardActivityList({
  items,
  hint,
}: {
  items: {
    key: string;
    to: string;
    title: string;
    detail: string;
    status?: string;
    thumbnail?: boolean;
    fallback?: ReactNode;
    inspectLabel: string;
    action?: (current: boolean) => ReactNode;
  }[];
  hint: string;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard<
    (typeof items)[number],
    HTMLUListElement
  >(items, (item) => item.key);
  return (
    <>
      <p id={labelId} className="dashboard-note">
        {hint}
      </p>
      <ul
        ref={listRef}
        className="activity-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {items.map((item, i) => (
          <ActivityRow
            key={item.key}
            to={item.to}
            title={item.title}
            detail={item.detail}
            status={item.status}
            thumbnail={item.thumbnail}
            fallback={item.fallback}
            inspectLabel={item.inspectLabel}
            inspectProps={itemProps(i, item.key)}
            current={i === index}
            action={item.action?.(i === index)}
          />
        ))}
      </ul>
    </>
  );
}

function attentionShortId(item: AttentionItem, kind: "inspect" | "action") {
  const id =
    kind === "action" && item.action === "read" ? item.noticeId : item.runId;
  return (id ?? item.key).slice(0, 8);
}

function attentionAction(
  item: AttentionItem,
  current: boolean,
  handlers: {
    acknowledgePending: boolean;
    cancelPending: boolean;
    readPending: boolean;
    decidePending: boolean;
    retryPending: boolean;
    onAcknowledge: (runId: string) => void;
    onStop: (runId: string) => void;
    onRead: (noticeId: string) => void;
    onDecide: (runId: string, resolution: "granted" | "denied") => void;
    onRetry: (runId: string) => void;
    onRetryWorkflow: (runId: string) => void;
    onSelect: () => void;
  },
) {
  const runId = item.runId;
  const noticeId = item.noticeId;
  const workflowId = item.retryWorkflowId;
  const actionId = attentionShortId(item, "action");
  const tagged = taggedAgentLinks(item.agentId, item.projectId, current, true);
  if (item.action === "acknowledge" && runId) {
    return (
      <>
        {tagged}
        {item.executorType === "photo_pipe" ? (
          <Button
            type="button"
            variant="secondary"
            tabIndex={current ? 0 : -1}
            disabled={handlers.retryPending}
            aria-label={`Retry as a new run ${item.title} ${actionId}`}
            onFocus={handlers.onSelect}
            onClick={() => handlers.onRetry(runId)}
          >
            Retry as a new run
          </Button>
        ) : null}
        <Button
          type="button"
          variant="secondary"
          tabIndex={current ? 0 : -1}
          disabled={handlers.acknowledgePending}
          aria-label={`Mark inspected ${item.title} ${actionId}`}
          onFocus={handlers.onSelect}
          onClick={() => handlers.onAcknowledge(runId)}
        >
          Mark inspected
        </Button>
      </>
    );
  }
  if (item.action === "stop" && runId) {
    return (
      <>
        {tagged}
        <Button
          type="button"
          variant="secondary"
          tabIndex={current ? 0 : -1}
          disabled={handlers.cancelPending}
          aria-label={`Stop ${item.title} ${actionId}`}
          onFocus={handlers.onSelect}
          onClick={() => handlers.onStop(runId)}
        >
          Stop
        </Button>
      </>
    );
  }
  if (item.action === "stopping") {
    return (
      <>
        {tagged}
        <span className="muted">Stopping…</span>
      </>
    );
  }
  if (item.action === "read" && noticeId) {
    return (
      <>
        {tagged}
        {workflowId ? (
          <Button
            type="button"
            variant="secondary"
            tabIndex={current ? 0 : -1}
            disabled={handlers.retryPending}
            aria-label={`Retry as a new workflow ${item.title} ${actionId}`}
            onFocus={handlers.onSelect}
            onClick={() => handlers.onRetryWorkflow(workflowId)}
          >
            Retry as a new workflow
          </Button>
        ) : null}
        <Button
          type="button"
          variant="secondary"
          tabIndex={current ? 0 : -1}
          disabled={handlers.readPending}
          aria-label={`Mark read ${item.title} ${actionId}`}
          onFocus={handlers.onSelect}
          onClick={() => handlers.onRead(noticeId)}
        >
          Mark read
        </Button>
      </>
    );
  }
  if (item.action === "approve" && runId) {
    return (
      <>
        {tagged}
        <Button
          type="button"
          tabIndex={current ? 0 : -1}
          disabled={handlers.decidePending}
          aria-label={`Approve and queue ${item.title} ${actionId}`}
          onFocus={handlers.onSelect}
          onClick={() => handlers.onDecide(runId, "granted")}
        >
          Approve and queue
        </Button>
        <Button
          type="button"
          variant="secondary"
          tabIndex={current ? 0 : -1}
          disabled={handlers.decidePending}
          aria-label={`Deny ${item.title} ${actionId}`}
          onFocus={handlers.onSelect}
          onClick={() => handlers.onDecide(runId, "denied")}
        >
          Deny
        </Button>
      </>
    );
  }
  return undefined;
}

function AttentionList({
  items,
  acknowledgePending,
  cancelPending,
  readPending,
  decidePending,
  retryPending,
  onAcknowledge,
  onStop,
  onRead,
  onDecide,
  onRetry,
  onRetryWorkflow,
}: {
  items: AttentionItem[];
  acknowledgePending: boolean;
  cancelPending: boolean;
  readPending: boolean;
  decidePending: boolean;
  retryPending: boolean;
  onAcknowledge: (runId: string) => void;
  onStop: (runId: string) => void;
  onRead: (noticeId: string) => void;
  onDecide: (runId: string, resolution: "granted" | "denied") => void;
  onRetry: (runId: string) => void;
  onRetryWorkflow: (runId: string) => void;
}) {
  const labelId = useId();
  const { listRef, index, setSelectedKey, onKeyDown, itemProps } =
    useListKeyboard<AttentionItem, HTMLUListElement>(
      items,
      (item) => item.key,
    );
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an item while the list is focused. Enter inspects it.
        Stop, Retry as a new run, Retry as a new workflow, Mark inspected, Mark
        read, Approve and Deny stay on the selected row. Inspect agent, Inspect
        project and View tagged Runs stay on a notice or agent Run with a saved
        link. View tagged Runs stays on a saved agent even without a project.
        Inspect project and View tagged Runs stay on a coding or worktree
        Run with a saved project.
      </p>
      <ul
        ref={listRef}
        className="activity-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {items.map((item, i) => {
          const current = i === index;
          const inspectId = attentionShortId(item, "inspect");
          return (
            <ActivityRow
              key={item.key}
              to={item.to}
              title={item.title}
              detail={item.detail}
              status={item.status}
              inspectLabel={`Inspect ${item.title} ${inspectId}`}
              inspectProps={itemProps(i, item.key)}
              current={current}
              action={attentionAction(item, current, {
                acknowledgePending,
                cancelPending,
                readPending,
                decidePending,
                retryPending,
                onAcknowledge,
                onStop,
                onRead,
                onDecide,
                onRetry,
                onRetryWorkflow,
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
  const markRead = useMutation({
    mutationFn: (noticeId: string) =>
      api(`/notices/${noticeId}/read`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ read: true }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const decide = useMutation({
    mutationFn: ({
      runId,
      resolution,
    }: {
      runId: string;
      resolution: "granted" | "denied";
    }) =>
      api(`/runs/${runId}/approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const retryImage = useMutation({
    mutationFn: (runId: string) =>
      api(`/images/runs/${runId}/retry`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const retryWorkflow = useMutation({
    mutationFn: (runId: string) =>
      api(`/runs/${runId}/retry-workflow`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
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
      agentId: run.agent_id ?? undefined,
      projectId: run.project_id,
      executorType: run.executor_type,
    })),
    ...notices
      .filter((notice) => !interruptedIds.has(notice.run_id))
      .map((notice) => ({
        key: notice.id,
        to: `/runs/${notice.run_id}`,
        title: notice.title,
        detail: `${notice.kind.replaceAll("_", " ")} · ${time(notice.created_at)}`,
        action: "read" as const,
        noticeId: notice.id,
        runId: notice.run_id,
        agentId: notice.agent_id,
        projectId: notice.project_id,
        retryWorkflowId:
          notice.retry?.allowed && notice.retry.run_id
            ? notice.retry.run_id
            : undefined,
      })),
    ...active.map((run) => ({
      key: run.id,
      to: `/runs/${run.id}`,
      title: run.title,
      detail:
        run.status === "waiting_for_approval"
          ? `${run.executor_type} · grant queues the Run; deny cancels it`
          : `${run.executor_type} · ${run.execution_target}`,
      status: run.status,
      action:
        run.status === "waiting_for_approval"
          ? ("approve" as const)
          : CANCELABLE.has(run.status)
            ? ("stop" as const)
            : run.status === "cancel_requested"
              ? ("stopping" as const)
              : undefined,
      runId: run.id,
      agentId: run.agent_id ?? undefined,
      projectId: run.project_id,
    })),
  ];
  const attention = attentionItems.length;
  return (
    <div className="dashboard-activity">
      <ErrorNotice
        error={
          query.error ??
          acknowledge.error ??
          cancel.error ??
          markRead.error ??
          decide.error ??
          retryImage.error ??
          retryWorkflow.error
        }
      />
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
                readPending={markRead.isPending}
                decidePending={decide.isPending}
                retryPending={retryImage.isPending || retryWorkflow.isPending}
                onAcknowledge={(runId) => acknowledge.mutate(runId)}
                onStop={(runId) => cancel.mutate(runId)}
                onRead={(noticeId) => markRead.mutate(noticeId)}
                onDecide={(runId, resolution) =>
                  decide.mutate({ runId, resolution })
                }
                onRetry={(runId) => retryImage.mutate(runId)}
                onRetryWorkflow={(runId) => retryWorkflow.mutate(runId)}
              />
            ) : (
              <Empty title="Nothing needs you right now">
                Interrupted work, notices and in-progress Runs will appear here
                with Stop, Retry as a new run, Retry as a new workflow, Mark
                inspected, Mark read, Approve or Deny.
              </Empty>
            )}
          </Section>
          <Section
            title="Upcoming schedules"
            to="/agents"
            viewAll="View all scheduled agents"
          >
            {data.upcoming.length ? (
              <KeyboardActivityList
                hint="Arrow keys choose a schedule while the list is focused. Enter inspects the agent. Inspect project and View tagged Runs stay on a saved link. View tagged Runs stays on a saved agent even without a project. Linking does not grant coding, Git or repository access. This list does not Enable or Run now."
                items={data.upcoming.map((agent) => ({
                  key: agent.id,
                  to: `/agents/${agent.id}`,
                  title: agent.name,
                  detail: `${time(agent.next_run_at)} · ${agent.trigger}${
                    agent.overdue ? " · Due / waiting for scheduler" : ""
                  }${agent.project_id ? " · Linked project" : ""}`,
                  inspectLabel: `Inspect scheduled ${agent.name} ${agent.id.slice(0, 8)}`,
                  action: (current) => linkedProjectAction(agent, current),
                }))}
              />
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
              <KeyboardActivityList
                hint="Arrow keys choose an agent while the list is focused. Enter inspects it. Inspect project and View tagged Runs stay on a saved link. View tagged Runs stays on a saved agent even without a project. Linking does not grant coding, Git or repository access. This list does not Enable or Run now."
                items={data.agents.map((agent) => ({
                  key: agent.id,
                  to: `/agents/${agent.id}`,
                  title: agent.name,
                  detail: `${agent.model} · ${agent.trigger}${
                    agent.project_id ? " · Linked project" : ""
                  }`,
                  status: agent.last_status || undefined,
                  inspectLabel: `Inspect ${agent.name} ${agent.id.slice(0, 8)}`,
                  fallback: agent.last_status ? undefined : (
                    <span className="muted">Not run yet</span>
                  ),
                  action: (current) => linkedProjectAction(agent, current),
                }))}
              />
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
              <KeyboardActivityList
                hint="Arrow keys choose a conversation while the list is focused. Enter opens it."
                items={data.conversations.map((conversation) => ({
                  key: conversation.id,
                  to: `/chat/${conversation.id}`,
                  title: conversation.title,
                  detail: `${conversation.model} · ${time(conversation.updated_at)}`,
                  inspectLabel: `Inspect ${conversation.title} ${conversation.id.slice(0, 8)}`,
                }))}
              />
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
              <KeyboardActivityList
                hint="Arrow keys choose an artifact while the list is focused. Enter inspects it."
                items={data.artifacts.map((artifact) => ({
                  key: artifact.id,
                  to: `/library/${artifact.id}`,
                  title: artifact.name,
                  detail: `${artifact.type} · ${time(artifact.created_at)}`,
                  thumbnail: artifact.has_thumbnail,
                  inspectLabel: `Inspect ${artifact.name} ${artifact.id.slice(0, 8)}`,
                }))}
              />
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
              <KeyboardActivityList
                hint="Arrow keys choose an observation while the list is focused. Enter opens System. There is no inspectable observation Run from Home."
                items={data.runtimes.map((runtime) => ({
                  key: runtime.id,
                  to: "/system",
                  title: runtime.name,
                  detail: `${runtime.ownership} · ${
                    runtime.source === "host_process" ? "Process" : "Endpoint"
                  } · ${time(runtime.updated_at)}${
                    runtime.stale ? " · Stale" : ""
                  }`,
                  status: runtime.status,
                  inspectLabel: `Inspect observation ${runtime.name} ${runtime.id.slice(0, 8)}`,
                }))}
              />
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
