import { Link } from "react-router-dom";
import { Badge } from "../components/common";

export default function AgentControlRun({
  run,
  tabIndex = 0,
}: {
  run: { id: string; status: string };
  tabIndex?: number;
}) {
  return (
    <div
      className="conversation-source-note"
      aria-label="Linked agent execution"
    >
      <Badge status={run.status} />{" "}
      <Link to={`/runs/${run.id}`} tabIndex={tabIndex}>
        Inspect agent execution
      </Link>
      {run.status === "cancel_requested" && (
        <span> · Stopping; waiting for owned work to finish.</span>
      )}
      {run.status === "waiting_for_approval" && (
        <span> · Review the requested approval before execution.</span>
      )}
    </div>
  );
}
