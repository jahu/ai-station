import { Link } from "react-router-dom";
import { Badge } from "../components/common";

export default function AgentControlRun({
  run,
  result,
  tabIndex = 0,
}: {
  run?: {
    id: string;
    status: string;
    delivery_status?: string;
    delivery_run_id?: string;
  };
  result: { agent_id: string; outcome: string };
  tabIndex?: number;
}) {
  return (
    <div
      className="conversation-source-note"
      aria-label="Linked agent execution"
    >
      <Link
        to={`/agents/${result.agent_id}?view=${result.outcome === "needs_review" ? "settings" : "workspace"}`}
        tabIndex={tabIndex}
      >
        {result.outcome === "needs_review"
          ? "Review & enable agent"
          : "Open agent workspace"}
      </Link>
      {run && (
        <>
          <Badge status={run.status} />{" "}
          <Link to={`/runs/${run.id}`} tabIndex={tabIndex}>
            Inspect agent execution
          </Link>
        </>
      )}
      {run?.delivery_status && (
        <span>
          {" · Email delivery: "}
          {run.delivery_status.replaceAll("_", " ")}
          {run.delivery_run_id && (
            <>
              {" · "}
              <Link to={`/runs/${run.delivery_run_id}`} tabIndex={tabIndex}>
                Inspect delivery
              </Link>
            </>
          )}
        </span>
      )}
      {run?.status === "cancel_requested" && (
        <span> · Stopping; waiting for owned work to finish.</span>
      )}
      {run?.status === "waiting_for_approval" && (
        <span> · Review the requested approval before execution.</span>
      )}
    </div>
  );
}
