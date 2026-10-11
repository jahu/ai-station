import { useId, useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

function runLabel(run: Run) {
  return run.capability === "agent.step"
    ? String(run.parameters?.tool ?? "step")
    : run.capability;
}

const CANCELABLE = new Set(["queued", "claimed", "preparing", "running"]);

export function RunApprovalActions({
  runId,
  name,
  tabIndex = 0,
  disabled,
}: {
  runId: string;
  name: string;
  tabIndex?: number;
  disabled?: boolean;
}) {
  const cache = useQueryClient();
  const decide = useMutation({
    mutationFn: (resolution: "granted" | "denied") =>
      api<Run>(`/runs/${runId}/approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["agent"] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      void cache.invalidateQueries({ queryKey: ["conversation"] });
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const shortId = runId.slice(0, 8);
  return (
    <>
      <ErrorNotice error={decide.error} />
      <Button
        type="button"
        disabled={disabled || decide.isPending}
        tabIndex={tabIndex}
        aria-label={`Approve and queue ${name} ${shortId}`}
        onClick={() => decide.mutate("granted")}
      >
        Approve and queue
      </Button>
      <Button
        type="button"
        variant="secondary"
        disabled={disabled || decide.isPending}
        tabIndex={tabIndex}
        aria-label={`Deny ${name} ${shortId}`}
        onClick={() => decide.mutate("denied")}
      >
        Deny
      </Button>
    </>
  );
}

export function AgentExecutionHistory({
  runs,
  tabIndex = 0,
  hint = "Arrow keys choose a Run while the list is focused. Enter inspects it. Stop stays on an in-progress Run. Approve and queue or Deny stays on a waiting Run. Retry as a new workflow stays on a failed snapshot when the saved policy allows it. Workflow steps of the last parent stay next to this history.",
}: {
  runs: Run[];
  tabIndex?: number;
  hint?: string;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [queued, setQueued] = useState<Run | null>(null);
  const retry = useMutation({
    mutationFn: (runId: string) =>
      api<Run>(`/runs/${runId}/retry-workflow`, { method: "POST" }),
    onSuccess: (result) => {
      setQueued(result);
      void cache.invalidateQueries({ queryKey: ["agent"] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const cancel = useMutation({
    mutationFn: (runId: string) =>
      api<Run>(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["agent"] });
      void cache.invalidateQueries({ queryKey: ["agents"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      void cache.invalidateQueries({ queryKey: ["conversation"] });
      void cache.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
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
      <ErrorNotice error={retry.error ?? cancel.error} />
      {queued ? (
        <p>
          Queued a new workflow from that snapshot.{" "}
          <Link
            className="text-link"
            to={`/runs/${queued.id}`}
            tabIndex={tabIndex}
            aria-label={`Inspect retry ${queued.id.slice(0, 8)}`}
          >
            Inspect retry
          </Link>
        </p>
      ) : null}
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
                {CANCELABLE.has(run.status) ? (
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cancel.isPending || retry.isPending}
                    tabIndex={active && current ? 0 : -1}
                    aria-label={`Stop ${label} ${shortId}`}
                    onClick={() => cancel.mutate(run.id)}
                  >
                    {cancel.isPending ? "Stopping…" : "Stop"}
                  </Button>
                ) : null}
                {run.status === "cancel_requested" ? (
                  <span className="muted">Stopping…</span>
                ) : null}
                {run.status === "waiting_for_approval" ? (
                  <RunApprovalActions
                    runId={run.id}
                    name={label}
                    tabIndex={active && current ? 0 : -1}
                    disabled={retry.isPending || cancel.isPending}
                  />
                ) : null}
                {run.retry?.allowed ? (
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={retry.isPending}
                    tabIndex={active && current ? 0 : -1}
                    aria-label={`Retry as a new workflow ${shortId}`}
                    onClick={() => retry.mutate(run.id)}
                  >
                    Retry as a new workflow
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <p className="muted">
        Latest 100 Runs. Stop targets the selected in-progress Run and does not
        call Run now. Approve and queue grants a parked Run without starting
        tools here. Deny cancels it. Manual retry queues a new workflow from the
        failed snapshot. It does not resume an uncertain step.
      </p>
    </section>
  );
}
