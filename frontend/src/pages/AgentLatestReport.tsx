import { useQuery } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import AgentReport from "./AgentReport";
import { SearchSources, type WebSources } from "./ChatWebSearch";

const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);

function latestAgentReportRun(runs: Run[]) {
  return runs.find((run) => run.executor_type === "agent") ?? null;
}

function isWebSources(value: unknown): value is WebSources {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.query === "string" &&
    typeof result.searched_at === "string" &&
    Array.isArray(result.sources)
  );
}

function latestSearchSources(runs: Run[], reportRun: Run): WebSources | null {
  if (isWebSources(reportRun.metadata?.web_search)) {
    return reportRun.metadata.web_search;
  }
  const parentId = reportRun.parent_run_id;
  if (!parentId) return null;
  const sibling = runs.find(
    (run) =>
      run.parent_run_id === parentId &&
      run.parameters?.tool === "web_search" &&
      isWebSources(run.metadata?.web_search),
  );
  return sibling && isWebSources(sibling.metadata?.web_search)
    ? sibling.metadata.web_search
    : null;
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
  const search = latestSearchSources(runs, reportRun);
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
      {search ? <SearchSources result={search} /> : null}
    </>
  );
}
