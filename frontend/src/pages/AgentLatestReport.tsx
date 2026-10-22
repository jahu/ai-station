import { useQuery } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import AgentReport from "./AgentReport";
import { FetchedPages, type FetchResult } from "./AgentHttpFetch";
import { RegistryToolCalls, type RegistryToolCall } from "./AgentToolCalls";
import { SearchSources, type WebSources } from "./ChatWebSearch";

import { BrowserPages } from "./BrowserPages";
import { isBrowserResult } from "./browserResult";

const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);

function latestAgentReportRun(runs: Run[]) {
  return (
    runs.find(
      (run) =>
        run.executor_type === "agent" ||
        (run.executor_type === "agent_market" &&
          run.parameters?.tool === "market.report"),
    ) ?? null
  );
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

function isRegistryToolCalls(value: unknown): value is RegistryToolCall[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        item &&
        typeof item === "object" &&
        typeof item.id === "string" &&
        typeof item.tool === "string" &&
        typeof item.round === "number",
    )
  );
}

function isFetchResult(value: unknown): value is FetchResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    Array.isArray(result.urls) &&
    typeof result.fetched_at === "string" &&
    Array.isArray(result.pages)
  );
}

function latestToolMetadata<T>(
  runs: Run[],
  reportRun: Run,
  tool: string,
  key: "web_search" | "http_fetch" | "browser",
  guard: (value: unknown) => value is T,
): T | null {
  const fromReport = reportRun.metadata?.[key];
  if (guard(fromReport)) return fromReport;
  const parentId = reportRun.parent_run_id;
  if (!parentId) return null;
  const sibling = runs.find(
    (run) =>
      run.parent_run_id === parentId &&
      run.parameters?.tool === tool &&
      guard(run.metadata?.[key]),
  );
  const fromSibling = sibling?.metadata?.[key];
  return guard(fromSibling) ? fromSibling : null;
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
  const search = latestToolMetadata(
    runs,
    reportRun,
    "web_search",
    "web_search",
    isWebSources,
  );
  const pages = latestToolMetadata(
    runs,
    reportRun,
    "http_fetch",
    "http_fetch",
    isFetchResult,
  );
  const browser = latestToolMetadata(
    runs,
    reportRun,
    "browser",
    "browser",
    isBrowserResult,
  );
  const recordedCalls = reportRun.metadata?.tool_calls;
  const calls = isRegistryToolCalls(recordedCalls) ? recordedCalls : [];
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
      {pages ? <FetchedPages result={pages} /> : null}
      {browser ? <BrowserPages result={browser} /> : null}
      {calls.length ? <RegistryToolCalls calls={calls} /> : null}
    </>
  );
}
