import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { terminal } from "../lib/utils";

export default function RepeatCodingChecks({
  source,
  validation,
}: {
  source: Run;
  validation?: Run;
}) {
  const cache = useQueryClient();
  const repeat = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/runs/${source.id}/checks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_validation_run_id: validation?.id }),
      }),
    onSettled: () => {
      for (const queryKey of [
        ["run", source.id],
        ["coding-session", source.task_id],
        ["coding-sessions"],
        ["conversation"],
        ["runs"],
      ])
        void cache.invalidateQueries({ queryKey });
    },
  });
  const superseded =
    source.metadata?.continuation_run_id ||
    source.metadata?.repair_run_id ||
    validation?.metadata?.repair_run_id;
  if (
    source.status !== "succeeded" ||
    superseded ||
    !validation ||
    !terminal.has(validation.status)
  )
    return null;
  const undispatched =
    ["failed", "canceled"].includes(validation.status) &&
    !validation.metadata?.dispatch_attempted &&
    !validation.pid &&
    !validation.process_group_id &&
    !validation.runner_id &&
    !validation.started_at;
  const safe =
    validation.metadata?.process_confirmed_gone === true || undispatched;
  if (!safe)
    return (
      <p className="muted">
        Inspect the previous check process before repeating checks.
      </p>
    );
  if (
    !Array.isArray(validation.parameters?.commands) ||
    !validation.parameters.commands.length
  )
    return null;
  const previous = validation.parameters?.rerun_of;
  return (
    <div
      className="coding-repeat-checks"
      role="group"
      aria-label="Repeat project checks"
    >
      <ErrorNotice error={repeat.error} />
      {repeat.data ? (
        <p>
          <Link className="text-link" to={`/runs/${repeat.data.id}`}>
            Checks queued · inspect execution →
          </Link>
        </p>
      ) : (
        <Button
          type="button"
          variant="secondary"
          disabled={repeat.isPending}
          onClick={() => repeat.mutate()}
        >
          <RotateCw size={15} />
          {repeat.isPending ? "Queuing checks…" : "Run checks again"}
        </Button>
      )}
      <p className="muted">
        Repeat the recorded commands in this workspace. No model or dependency
        installation.
      </p>
      {typeof previous === "string" && (
        <Link className="text-link" to={`/runs/${previous}`}>
          Previous checks →
        </Link>
      )}
    </div>
  );
}
