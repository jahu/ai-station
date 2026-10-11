import { useId, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { type Run } from "../api";
import { Badge } from "../components/common";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

function runLabel(run: Run) {
  return run.capability === "agent.step"
    ? String(run.parameters?.tool ?? "step")
    : run.capability;
}

export function AgentExecutionHistory({
  runs,
  tabIndex = 0,
  hint = "Arrow keys choose a Run while the list is focused. Enter inspects it.",
}: {
  runs: Run[];
  tabIndex?: number;
  hint?: string;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    runs,
    (run) => run.id,
  );
  const selected = runs[index];
  const active = tabIndex >= 0;
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.id) {
      event.preventDefault();
      navigate(`/runs/${selected.id}`);
    }
  };
  return (
    <section className="panel agent-form" aria-labelledby={headingId}>
      <h2 id={headingId}>Execution history</h2>
      <p id={labelId} className="dashboard-note">
        {hint}
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {runs.map((run, i) => {
          const current = i === index;
          const shortId = run.id.slice(0, 8);
          const label = runLabel(run);
          const props = itemProps(i, run.id);
          return (
            <div key={run.id} {...props} tabIndex={active && current ? 0 : -1}>
              <div>
                <strong>{label}</strong>
                <p>{time(run.created_at)}</p>
              </div>
              <div className="row">
                <Badge status={run.status} />
                <Link
                  className="text-link"
                  to={`/runs/${run.id}`}
                  tabIndex={active && current ? 0 : -1}
                  aria-label={`Inspect ${label} ${shortId}`}
                >
                  {shortId}
                </Link>
              </div>
            </div>
          );
        })}
      </div>
      <p className="muted">
        Latest 100 Runs. Open a Run to inspect events, parameters, errors, and
        report artifacts.
      </p>
    </section>
  );
}
