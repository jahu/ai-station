import { Link } from "react-router-dom";
import type { Run } from "../api";
import { CodingConversation } from "./CodingSessions";

const PROPOSALS = ["local_proposal", "cursor_proposal", "codex_proposal"];

export default function AgentCodeWorkspace({ runs }: { runs: Run[] }) {
  const taskId = runs[0]?.task_id;
  if (!taskId) return null;
  const hasConversation = runs.some(
    (run) =>
      run.task_id === taskId &&
      (PROPOSALS.includes(run.executor_type) ||
        (typeof run.metadata?.next_executor === "string" &&
          PROPOSALS.includes(run.metadata.next_executor))),
  );
  return (
    <section className="agent-code-workspace" aria-label="Agent code workspace">
      <header>
        <div>
          <h2>Code and files</h2>
          <p className="muted">
            Results, checks and follow-up instructions in the same workspace.
          </p>
        </div>
        {hasConversation && (
          <Link to={`/coding/${taskId}`} className="text-link">
            Open task history
          </Link>
        )}
      </header>
      {hasConversation ? (
        <CodingConversation key={taskId} id={taskId} embedded />
      ) : (
        <p className="muted">
          Preparing the workspace. Progress and execution details appear below.
        </p>
      )}
    </section>
  );
}
