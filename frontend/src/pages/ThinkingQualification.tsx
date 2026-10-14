import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

export default function ThinkingQualification({
  model,
  disabled,
}: {
  model: string;
  disabled?: boolean;
}) {
  const cache = useQueryClient();
  const [runId, setRunId] = useState("");
  const start = useMutation({
    mutationFn: () =>
      api<Run>(
        `/llama/models/${model.replace(/^llamacpp:/, "")}/reasoning-check`,
        { method: "POST" },
      ),
    onSuccess: (run) => setRunId(run.id),
  });
  const run = useQuery({
    queryKey: ["thinking-check", runId],
    queryFn: () => api<Run>("/runs/" + runId),
    enabled: !!runId,
    refetchInterval: (query) =>
      ["succeeded", "failed", "canceled", "interrupted"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 1000,
  });
  const cancel = useMutation({
    mutationFn: () => api<Run>(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () =>
      cache.invalidateQueries({ queryKey: ["thinking-check", runId] }),
  });
  useEffect(() => {
    if (run.data?.status === "succeeded")
      void cache.invalidateQueries({ queryKey: ["chat-model-catalog"] });
  }, [run.data?.status, cache]);
  const active =
    !!runId &&
    !["succeeded", "failed", "canceled", "interrupted"].includes(
      run.data?.status ?? "",
    );
  return (
    <div className="thinking-qualification">
      <p className="muted">
        Check this model with two short local replies before enabling thinking
        controls.
      </p>
      <Button
        type="button"
        variant="secondary"
        disabled={disabled || start.isPending || active}
        onClick={() => start.mutate()}
      >
        {start.isPending || active
          ? "Checking thinking…"
          : "Check thinking support"}
      </Button>
      {run.data && (
        <div className="row">
          <Badge status={run.data.status} />
          <Link to={`/runs/${runId}`}>Inspect check</Link>
          {active && (
            <Button
              type="button"
              variant="ghost"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Stop check
            </Button>
          )}
        </div>
      )}
      <ErrorNotice error={start.error ?? run.error ?? cancel.error} />
      {run.data?.error_message && (
        <p className="notice">{run.data.error_message}</p>
      )}
    </div>
  );
}
