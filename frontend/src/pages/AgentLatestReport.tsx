import { useQuery } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import AgentReport from "./AgentReport";

const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);

function latestAgentReportRun(runs: Run[]) {
  return runs.find((run) => run.executor_type === "agent") ?? null;
}

export function AgentLatestReport({ runs }: { runs: Run[] }) {
  const reportRun = latestAgentReportRun(runs);
  const artifacts = useQuery({
    queryKey: ["run-artifacts", reportRun?.id],
    enabled: !!reportRun,
    queryFn: () => api<Artifact[]>(`/artifacts?run_id=${reportRun!.id}`),
    refetchInterval:
      reportRun && !TERMINAL.has(reportRun.status) ? 3000 : false,
  });
  if (!reportRun) return null;
  return (
    <>
      <ErrorNotice error={artifacts.error} />
      {artifacts.data ? (
        <AgentReport
          artifacts={artifacts.data}
          memoryId={
            typeof reportRun.metadata?.memory_entry_id === "string"
              ? reportRun.metadata.memory_entry_id
              : undefined
          }
          excerpted={reportRun.metadata?.memory_excerpted === true}
        />
      ) : null}
    </>
  );
}
