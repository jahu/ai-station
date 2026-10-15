import { CheckCircle2, Circle, CircleAlert, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import type { Run } from "../api";
import { terminal } from "../lib/utils";

type Step = { label: string; runs: Run[]; missing: string };
const proposals = new Set([
  "local_proposal",
  "cursor_proposal",
  "codex_proposal",
]);
const labels: Record<string, string> = {
  project_setup: "Creating project",
  worktree_prepare: "Preparing workspace",
  llama_load: "Loading local model",
  local_proposal: "Local AI is coding",
  cursor_proposal: "Cursor is coding",
  codex_proposal: "Codex is coding",
  project_plan: "Preparing project checks",
  project_dependencies: "Installing dependencies",
  project_validation: "Running project checks",
  reviewed_commit: "Saving reviewed changes",
  github_publication: "Publishing reviewed changes",
};
function stage(step: Step) {
  const active = step.runs.find((r) => !terminal.has(r.status));
  const failed = step.runs.find(
    (r) => r.status === "failed" || r.status === "interrupted",
  );
  const canceled = step.runs.find((r) => r.status === "canceled");
  const run = active ?? failed ?? canceled ?? step.runs.at(-1);
  return {
    run,
    state: active
      ? "active"
      : failed
        ? "failed"
        : canceled
          ? "canceled"
          : run
            ? "succeeded"
            : "pending",
    text: active
      ? active.status.replaceAll("_", " ")
      : failed
        ? "Failed"
        : canceled
          ? "Stopped"
          : run
            ? "Done"
            : step.missing,
  };
}

export default function CodingTaskProgress({ runs }: { runs: Run[] }) {
  const latest = [...runs]
    .reverse()
    .find((r) => proposals.has(r.executor_type));
  const byId = (id: unknown) =>
    typeof id === "string" ? runs.filter((r) => r.id === id) : [];
  const unfinished = [...runs].reverse().filter((r) => !terminal.has(r.status));
  const active =
    unfinished.find((r) => r.status === "cancel_requested") ??
    unfinished.find((r) => r.status === "waiting_for_approval") ??
    unfinished.find((r) =>
      ["running", "preparing", "claimed"].includes(r.status),
    ) ??
    unfinished[0];
  const policy = latest?.parameters.project_check_policy as
    | { auto_install_dependencies?: boolean; auto_validate?: boolean }
    | undefined;
  const metadata = latest?.metadata ?? {};
  const plan = byId(metadata.project_plan_run_id);
  const dependencyIds = Array.isArray(metadata.dependency_run_ids)
    ? metadata.dependency_run_ids
    : [];
  const dependencies = runs.filter((r) => dependencyIds.includes(r.id));
  const checks = byId(metadata.validation_run_id);
  const worktree = byId(latest?.parameters.worktree_run_id);
  const workspace = worktree.length
    ? worktree
    : runs.filter((r) =>
        ["project_setup", "worktree_prepare"].includes(r.executor_type),
      );
  const modelLoads = runs.filter(
    (r) =>
      r.executor_type === "llama_load" &&
      (!latest || r.created_at >= latest.created_at),
  );
  const stopped = [
    ...workspace,
    latest,
    ...plan,
    ...dependencies,
    ...checks,
  ].some((r) => r?.status === "canceled");
  const notStarted =
    stopped || latest?.status === "failed" ? "Not run" : "Not started";
  const steps: Step[] = [
    {
      label: "Workspace",
      runs: workspace,
      missing: notStarted,
    },
    ...(modelLoads.length
      ? [{ label: "Local model", runs: modelLoads, missing: notStarted }]
      : []),
    { label: "Code", runs: latest ? [latest] : [], missing: notStarted },
    ...(policy?.auto_install_dependencies || dependencies.length
      ? [
          {
            label: "Dependencies",
            runs: [...plan, ...dependencies],
            missing: notStarted,
          },
        ]
      : []),
    {
      label: "Checks",
      runs: checks,
      missing: policy?.auto_validate ? notStarted : "Not configured",
    },
  ];
  const failed = [
    ...workspace,
    latest,
    ...plan,
    ...dependencies,
    ...checks,
  ].find((r) => r && (r.status === "failed" || r.status === "interrupted"));
  const verified =
    checks.length > 0 && checks.every((r) => r.status === "succeeded");
  const report = checks.at(-1)?.metadata?.validation as
    { commands?: { kind?: string }[] } | undefined;
  const noTests =
    Array.isArray(report?.commands) &&
    !report.commands.some((command) => command.kind === "test");
  const title = active
    ? active.status === "cancel_requested"
      ? "Stopping task"
      : active.status === "waiting_for_approval"
        ? "Approval needed"
        : active.status === "queued"
          ? "Task queued"
          : (labels[active.executor_type] ?? "Task in progress")
    : failed
      ? "Task needs attention"
      : stopped
        ? "Task stopped"
        : verified
          ? "Checks passed · ready for review"
          : latest?.status === "succeeded"
            ? "Changes ready · not tested"
            : "Preparing workspace";
  const description = active
    ? "You can inspect each stage below while the task continues."
    : failed
      ? failed.error_message || "Inspect the failed stage before continuing."
      : stopped
        ? "Your workspace and conversation are preserved."
        : verified
          ? noTests
            ? "Build checks passed. No automated tests were recorded. Review the diff before committing."
            : "Review the diff before committing or publishing."
          : latest?.status === "succeeded"
            ? "No successful checks are recorded for this turn. Review and test before committing."
            : "The agent will use an isolated task workspace.";
  const model = latest?.parameters.model_selection as
    { name?: string; context_size?: number } | undefined;
  return (
    <section className="panel coding-progress" aria-label="Task progress">
      <div className="coding-progress-heading" role="status">
        <h2>{title}</h2>
        <p className="muted">{description}</p>
      </div>
      {model?.name && (
        <p className="coding-progress-model">
          Local · {model.name}
          {model.context_size
            ? ` · ${model.context_size.toLocaleString("en-US")} context`
            : ""}
        </p>
      )}
      <ol className="coding-progress-steps">
        {steps.map((step) => {
          const state = stage(step);
          const Icon =
            state.state === "active"
              ? LoaderCircle
              : state.state === "succeeded"
                ? CheckCircle2
                : state.state === "failed"
                  ? CircleAlert
                  : Circle;
          return (
            <li key={step.label} data-state={state.state}>
              <Icon size={17} aria-hidden="true" />
              <div>
                <strong>{step.label}</strong>
                <small>{state.text}</small>
              </div>
              {state.run && (
                <Link
                  to={`/runs/${state.run.id}`}
                  className="coding-progress-inspect"
                  aria-label={`Inspect ${step.label.toLowerCase()}`}
                >
                  ↗
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
