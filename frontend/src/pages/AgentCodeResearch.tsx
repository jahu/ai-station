import type { Run } from "../api";
import { Link } from "react-router-dom";
import { AgentSearchSources } from "./AgentSearchSources";
import { isSearchPageResult } from "./agent-search-result";
import { FetchedPages } from "./AgentHttpFetch";
import { SearchSources } from "./ChatWebSearch";
import { isFetchResult, isWebSources } from "./agentResearchResult";
import { BrowserPages } from "./BrowserPages";
import { isBrowserResult } from "./browserResult";

export default function AgentCodeResearch({
  runs,
  taskId,
}: {
  runs: Run[];
  taskId: string;
}) {
  const handoff = runs.find(
    (run) =>
      run.task_id === taskId && run.executor_type === "agent_page_coding",
  );
  if (!handoff) return null;
  const rawIds = handoff.parameters?.source_run_ids;
  const ids =
    Array.isArray(rawIds) && rawIds.every((id) => typeof id === "string")
      ? rawIds
      : typeof handoff.parameters?.source_run_id === "string"
        ? [handoff.parameters.source_run_id]
        : [];
  const sources = runs.filter(
    (run) =>
      ids.includes(run.id) &&
      run.task_id === taskId &&
      run.parent_run_id === handoff.parent_run_id &&
      run.agent_id === handoff.agent_id &&
      run.project_id === handoff.project_id &&
      (run.executor_type === "agent_tool" ||
        (run.executor_type === "browser" &&
          run.parameters?.tool === "browser")) &&
      run.status === "succeeded",
  );
  const search = sources.find((run) => run.parameters?.tool === "web_search")
    ?.metadata?.web_search;
  const pages = sources.find((run) => run.parameters?.tool === "search_pages")
    ?.metadata?.search_pages;
  const fetchedRun = sources.find(
    (run) => run.parameters?.tool === "http_fetch",
  );
  const fetched = fetchedRun?.metadata?.http_fetch;
  const rendered = sources.find((run) => run.parameters?.tool === "browser")
    ?.metadata?.browser;
  const observation = fetchedRun?.metadata?.observation;
  const fetchedSnapshot =
    observation &&
    typeof observation === "object" &&
    "artifact_id" in observation
      ? observation.artifact_id
      : undefined;
  const hasSearch = isWebSources(search),
    hasPages = isSearchPageResult(pages),
    hasFetched = isFetchResult(fetched),
    hasRendered = isBrowserResult(rendered);
  if (!hasSearch && !hasPages && !hasFetched && !hasRendered) return null;
  return (
    <details
      className="panel web-search-sources"
      aria-label="Research for this task"
    >
      <summary>
        Research sources
        {hasPages && pages.partial ? " · Some pages unavailable" : ""}
      </summary>
      <p className="muted">
        References for this task. Search results and opened pages are listed
        separately.
      </p>
      {hasSearch && <SearchSources result={search} />}
      {hasPages && <AgentSearchSources result={pages} />}
      {hasFetched && <FetchedPages result={fetched} />}
      {hasRendered && (
        <>
          <p className="muted">
            Local work uses captured page text. Screenshots are saved for your
            inspection; their pixels were not analyzed by the model.
          </p>
          <BrowserPages result={rendered} />
        </>
      )}
      {hasFetched && typeof fetchedSnapshot === "string" && (
        <Link className="text-link" to={`/library/${fetchedSnapshot}`}>
          Inspect captured pages
        </Link>
      )}
    </details>
  );
}
