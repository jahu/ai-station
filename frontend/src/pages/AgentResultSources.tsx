import { Link } from "react-router-dom";

export type AgentResultSource = {
  source_message_id: string;
  workflow_run_id: string;
  run_id?: string;
  available: boolean;
  status: string;
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
        ? "Using a stored agent report"
        : source.status === "succeeded"
          ? "Agent report unavailable"
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
