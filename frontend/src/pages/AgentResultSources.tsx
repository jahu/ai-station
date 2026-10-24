import { Link } from "react-router-dom";

export type AgentResultSource = {
  source_message_id: string;
  workflow_run_id: string;
  run_id?: string;
  available: boolean;
  status: string;
  family?: "report" | "data" | "coding" | "media";
  inspection?: "publication_metadata_only";
  included_characters?: number;
  total_characters?: number;
  truncated?: boolean;
};

export default function AgentResultSources({
  sources,
  tabIndex = 0,
}: {
  sources?: AgentResultSource[];
  tabIndex?: number;
}) {
  return sources?.map((source) => (
    <p className="muted" key={source.source_message_id}>
      {source.available
        ? source.family === "data"
          ? "Using a stored agent data result"
          : source.family === "coding"
            ? "Using a stored coding review"
            : source.family === "media"
              ? "Using published media metadata · contents not inspected"
              : "Using a stored agent report"
        : source.status === "succeeded"
          ? source.family && source.family !== "report"
            ? "Agent result unavailable"
            : "Agent report unavailable"
          : `Agent execution: ${source.status.replaceAll("_", " ")}`}
      {source.truncated &&
        ` · excerpt ${source.included_characters} / ${source.total_characters} characters`}
      {" · "}
      <Link
        to={`/runs/${source.run_id ?? source.workflow_run_id}`}
        tabIndex={tabIndex}
        aria-label={`Inspect agent result source ${(source.run_id ?? source.workflow_run_id).slice(0, 8)}`}
      >
        Inspect source
      </Link>
    </p>
  ));
}
