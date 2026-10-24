import { Link } from "react-router-dom";
import "./DataAgentDraftSource.css";
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
  const selected = source.kind === "selected_inputs";
  const data = definition.data as Record<string, unknown> | undefined;
  const creation = data?.operation === "create";
  const labels = [source.input_names, source.documents].flatMap((values) =>
    Array.isArray(values)
      ? values.filter((name): name is string => typeof name === "string")
      : [],
  );
  return (
    <section
      className="panel agent-document-sources data-agent-draft-source"
      aria-label={
        selected
          ? "Selected inputs for this agent"
          : "Original analysis for this agent"
      }
    >
      <h3>
        {selected
          ? "Inputs selected for this agent"
          : "Drafted from this analysis"}
      </h3>
      <p className="muted">
        {selected
          ? "Saved creation request and input selection."
          : "Saved source snapshot."}{" "}
        Later edits to the agent definition do not rewrite it.
      </p>
      <p className="agent-document-preview">
        {definition.goal.slice(0, 600)}
        {definition.goal.length > 600 ? "…" : ""}
      </p>
      {definition.goal.length > 600 && (
        <details className="agent-memory-capture">
          <summary>
            {selected ? "Creation request" : "Original analysis instruction"}
          </summary>
          <pre>{definition.goal}</pre>
        </details>
      )}
      {labels.length > 0 && (
        <p className="muted agent-document-preview">
          Selected files: {labels.join(", ")}
        </p>
      )}
      <p className="muted">
        {creation
          ? "At creation, the draft selected file creation from instructions, without reading existing files."
          : source.live_public_sources === true
            ? "At creation, the draft retained live public sources for each execution."
            : "At creation, the draft retained selected saved files or captured data."}{" "}
        The agent will use its own private workspace. Review the schedule and
        enable it when ready.
      </p>
      <p className="muted">Retained tools: {definition.tools.join(", ")}</p>
      <Link
        className="text-link"
        to={`/runs/${encodeURIComponent(source.source_run_id)}`}
      >
        {selected ? "Inspect agent creation" : "Inspect original analysis"}
      </Link>
    </section>
  );
}
