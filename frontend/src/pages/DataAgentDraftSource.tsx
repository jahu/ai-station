import { Link } from "react-router-dom";
import "./AgentDocumentSources.css";
import "./AgentMemorySources.css";

export default function DataAgentDraftSource({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const source = value as Record<string, unknown>;
  const definition = source.definition as Record<string, unknown> | undefined;
  if (
    typeof source.source_run_id !== "string" ||
    !definition ||
    typeof definition.goal !== "string" ||
    !Array.isArray(definition.tools) ||
    !definition.tools.every((name) => typeof name === "string")
  )
    return null;
  const labels = [source.input_names, source.documents].flatMap((values) =>
    Array.isArray(values)
      ? values.filter((name): name is string => typeof name === "string")
      : [],
  );
  return (
    <section
      className="panel agent-document-sources"
      aria-label="Original analysis for this agent"
    >
      <h3>Drafted from this analysis</h3>
      <p className="muted">
        Saved source snapshot. Later edits to the agent definition do not
        rewrite it.
      </p>
      <p className="agent-document-preview">
        {definition.goal.slice(0, 600)}
        {definition.goal.length > 600 ? "…" : ""}
      </p>
      {definition.goal.length > 600 && (
        <details className="agent-memory-capture">
          <summary>Original analysis instruction</summary>
          <pre>{definition.goal}</pre>
        </details>
      )}
      {labels.length > 0 && (
        <p className="muted agent-document-preview">
          Selected files: {labels.join(", ")}
        </p>
      )}
      <p className="muted">
        {source.live_public_sources === true
          ? "At creation, the draft retained live public sources for each execution."
          : "At creation, the draft retained selected saved files or captured data."}{" "}
        A new private workspace is created for the agent. Review the schedule
        and enable it when ready.
      </p>
      <p className="muted">Retained tools: {definition.tools.join(", ")}</p>
      <Link
        className="text-link"
        to={`/runs/${encodeURIComponent(source.source_run_id)}`}
      >
        Inspect original analysis
      </Link>
    </section>
  );
}
