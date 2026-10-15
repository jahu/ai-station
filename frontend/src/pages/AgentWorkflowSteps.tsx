import { useId, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { type Run } from "../api";
import { Badge } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";

export type Workflow = NonNullable<Run["workflow"]>;

function lastParentWorkflow(runs: Run[]): Workflow | null {
  const parent = runs.find(
    (run) =>
      run.executor_type === "agent_workflow" ||
      run.capability === "agent.workflow",
  );
  return parent?.workflow ?? null;
}

export function WorkflowStepCards({
  workflow,
  tabIndex = 0,
  inspectPrefix = "Inspect",
  extra = "Cancel targets the currently active child. Saved observations open Memory.",
  hint = "Arrow keys choose a step while the list is focused. Enter inspects its child Run. A saved observation opens Memory. Cancel stays outside this list.",
}: {
  workflow: Workflow;
  tabIndex?: number;
  inspectPrefix?: string;
  extra?: string;
  hint?: string;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    workflow.steps,
    (step) => step.run_id,
  );
  const selected = workflow.steps[index];
  const active = tabIndex >= 0;
  const pageCoding = workflow.steps.some(
    (step) => step.capability === "agent.coding_context",
  );
  const pageCodingLabels: Record<string, string> = {
    "agent.step": "Read reviewed pages",
    "agent.coding_context": "Prepare coding context",
    "coding.prepare": "Prepare isolated workspace",
    "coding.local": "Implement changes",
  };
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.run_id) {
      event.preventDefault();
      navigate(`/runs/${selected.run_id}`);
    }
  };
  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>Workflow steps</h2>
      <p className="muted">
        {workflow.mode === "gated"
          ? "Gated: the requested work requires approval before execution."
          : "Sequential: each step waits for the previous one to succeed."}{" "}
        {workflow.tool_calling === "bounded"
          ? "The report may request selected registry tools; invented tools fail closed. "
          : ""}
        {extra}
      </p>
      {workflow.steps.length ? (
        <>
          <p id={labelId} className="dashboard-note">
            {hint}
          </p>
          <div
            ref={listRef}
            className="diagnostic-list"
            aria-labelledby={labelId}
            onKeyDown={handleKey}
          >
            {workflow.steps.map((step, i) => {
              const current = i === index;
              const shortId = step.run_id.slice(0, 8);
              const props = itemProps(i, step.run_id);
              return (
                <div
                  key={step.run_id}
                  {...props}
                  tabIndex={active && current ? 0 : -1}
                >
                  <div>
                    <strong>
                      {(pageCoding && pageCodingLabels[step.key]) || step.key}
                    </strong>
                    <p>
                      {step.capability}
                      {step.gate === "approval" ? " · approval gate" : ""}
                    </p>
                    {!!step.tool_calls?.length && (
                      <p>
                        {step.tool_calls.length} registry call
                        {step.tool_calls.length === 1 ? "" : "s"}
                      </p>
                    )}
                    {step.memory_id ? (
                      <p>
                        <Link
                          className="text-link"
                          to={`/memory/${step.memory_id}`}
                          tabIndex={active && current ? 0 : -1}
                          aria-label={`View saved observation ${step.key} ${step.memory_id.slice(0, 8)}`}
                        >
                          saved observation
                        </Link>
                        {step.memory_excerpted
                          ? " · Memory contains an excerpt"
                          : ""}
                      </p>
                    ) : null}
                  </div>
                  <div className="row">
                    <Badge status={step.status} />
                    <Link
                      className="text-link"
                      to={`/runs/${step.run_id}`}
                      tabIndex={active && current ? 0 : -1}
                      aria-label={`${inspectPrefix} ${step.key} ${shortId}`}
                    >
                      {shortId}
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      ) : (
        <p className="muted">
          Steps are published after this workflow Run starts.
        </p>
      )}
    </section>
  );
}

export function AgentLastWorkflowSteps({
  runs,
  tabIndex = 0,
}: {
  runs: Run[];
  tabIndex?: number;
}) {
  const workflow = lastParentWorkflow(runs);
  if (!workflow) return null;
  return (
    <WorkflowStepCards
      workflow={workflow}
      tabIndex={tabIndex}
      inspectPrefix="Inspect step"
      extra="Saved observations open Memory. Run now stays on the saved definition. Stop stays on execution history."
      hint="Arrow keys choose a step while the list is focused. Enter inspects its child Run. A saved observation opens Memory. Run now stays on the saved definition. Stop stays on execution history."
    />
  );
}
