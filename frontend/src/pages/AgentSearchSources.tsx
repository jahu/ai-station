import { Link } from "react-router-dom";
import { FetchedPages } from "./AgentHttpFetch";
import type { SearchPageResult } from "./agent-search-result";

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
          Some sources could not be read. Review the available sources before
          relying on the result.
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
