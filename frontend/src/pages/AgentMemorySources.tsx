import { Link } from "react-router-dom";
import type { Run } from "../api";

import { memoryObservation } from "./agentResearchResult";

export default function AgentMemorySources({ runs }: { runs: Run[] }) {
  return (
    <>
      {runs.map((run) => {
        const value = run.metadata?.observation;
        if (!memoryObservation(value)) return null;
        return (
          <section
            key={run.id}
            aria-label={
              value.scope === "agent"
                ? "This agent's captured memory"
                : "Linked project's captured memory"
            }
          >
            <h4>
              {value.scope === "agent"
                ? "This agent's memory"
                : "Linked project memory"}{" "}
              · {value.entries.length} saved observation
              {value.entries.length === 1 ? "" : "s"}
            </h4>
            <p className="muted">
              These saved versions were supplied to this task. Later edits do
              not rewrite this capture.
            </p>
            {value.entries.length ? (
              <ul className="source-list">
                {value.entries.map((entry) => (
                  <li key={entry.id}>
                    <p>
                      {entry.content.slice(0, 400)}
                      {entry.content.length > 400 ? "…" : ""}
                    </p>
                    <p className="muted">
                      Saved version ·{" "}
                      {new Date(entry.updated_at).toLocaleString()}
                    </p>
                    <div className="row">
                      <Link
                        className="text-link"
                        to={`/memory/${encodeURIComponent(entry.id)}`}
                      >
                        Inspect memory
                      </Link>
                      {typeof entry.source_run_id === "string" && (
                        <Link
                          className="text-link"
                          to={`/runs/${encodeURIComponent(entry.source_run_id)}`}
                        >
                          Original result
                        </Link>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No enabled observations were available in this scope.</p>
            )}
            <Link className="text-link" to={`/runs/${run.id}`}>
              Inspect memory capture
            </Link>
          </section>
        );
      })}
    </>
  );
}
