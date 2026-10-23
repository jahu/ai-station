import { Link } from "react-router-dom";
import { FetchedPages, type FetchResult } from "./AgentHttpFetch";

export type SearchPageResult = FetchResult & {
  query: string;
  partial: boolean;
  search_artifact_id: string;
  errors: { url: string; error: string }[];
};

export function isSearchPageResult(value: unknown): value is SearchPageResult {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.query === "string" &&
    typeof item.partial === "boolean" &&
    typeof item.search_artifact_id === "string" &&
    typeof item.fetched_at === "string" &&
    Array.isArray(item.urls) &&
    item.urls.every((url) => typeof url === "string") &&
    Array.isArray(item.pages) &&
    item.pages.every(
      (page) =>
        page &&
        typeof page === "object" &&
        typeof page.url === "string" &&
        (page.text === undefined || typeof page.text === "string") &&
        (page.error === undefined || typeof page.error === "string") &&
        (page.skipped === undefined || typeof page.skipped === "string"),
    ) &&
    Array.isArray(item.errors) &&
    item.errors.every(
      (error) =>
        error &&
        typeof error === "object" &&
        typeof error.url === "string" &&
        typeof error.error === "string",
    )
  );
}

export function AgentSearchSources({ result }: { result: SearchPageResult }) {
  const readable = result.pages.filter(
    (page) => page.text && !page.error && !page.skipped,
  ).length;
  return (
    <section
      className="agent-search-sources"
      aria-label="Search source reading"
    >
      <p className="muted">
        Public query: <strong>{result.query}</strong> · {readable} of{" "}
        {result.urls.length} sources provided text ·{" "}
        <Link to={`/library/${result.search_artifact_id}`}>
          Search snapshot
        </Link>
      </p>
      {result.partial && (
        <p className="notice" role="status">
          Some sources could not be read. The report distinguishes page excerpts
          from search snippets.
        </p>
      )}
      <FetchedPages result={result} label="Read search sources" />
      {result.errors.length > 0 && (
        <details className="web-search-sources">
          <summary>
            Unread sources <span className="chip">{result.errors.length}</span>
          </summary>
          {result.errors.map((item) => (
            <p className="muted" key={item.url}>
              <strong>{item.url}</strong> — {item.error}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}
