import { useId } from "react";
import { Globe, ExternalLink } from "lucide-react";
import { useListKeyboard } from "./useListKeyboard";

export type WebSources = {
  query: string;
  searched_at: string;
  partial: boolean;
  sources: { id: number; title: string; url: string; snippet: string }[];
};

export function WebSearchControl({
  enabled,
  query,
  busy,
  onToggle,
  onQuery,
}: {
  enabled: boolean;
  query: string;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onQuery: (query: string) => void;
}) {
  return (
    <div className="chat-web-search">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Search the web"
        disabled={busy}
        className="web-search-toggle"
        onClick={() => onToggle(!enabled)}
      >
        <Globe size={16} />
        <span>Search the web</span>
        <span className="chip">{enabled ? "ON" : "OFF"}</span>
      </button>
      {enabled && (
        <div className="web-search-query">
          <label>
            Search query <span className="muted">optional</span>
            <input
              aria-label="Search query"
              maxLength={500}
              value={query}
              disabled={busy}
              onChange={(e) => onQuery(e.target.value)}
              placeholder="Use my message as the search query"
            />
          </label>
          <p className="muted">
            Only this query is sent to search engines. Conversation history and
            attachments stay local.
          </p>
        </div>
      )}
    </div>
  );
}

export function SearchSources({ result }: { result: WebSources }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    result.sources,
    (source) => String(source.id),
  );
  return (
    <details className="web-search-sources" open>
      <summary>
        <Globe size={15} /> Sources{" "}
        <span className="chip">{result.sources.length}</span>
      </summary>
      <section aria-labelledby={headingId}>
        <h3 id={headingId} className="sr-only">
          Search sources
        </h3>
        <p className="muted">
          Searched: {result.query} ·{" "}
          <time dateTime={result.searched_at}>
            {new Date(result.searched_at).toLocaleString()}
          </time>
        </p>
        {result.sources.length ? (
          <>
            <p id={labelId} className="dashboard-note">
              Arrow keys choose a source while the list is focused. Enter opens
              the selected public URL. This is search, not browser automation.
            </p>
            <div
              ref={listRef}
              className="web-source-grid"
              aria-labelledby={labelId}
              onKeyDown={onKeyDown}
            >
              {result.sources.map((source, i) => (
                <a
                  key={source.id}
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="web-source-card"
                  aria-label={`Source ${source.title} ${source.id}`}
                  {...itemProps(i, String(source.id))}
                >
                  <span className="muted">
                    {source.id} · {new URL(source.url).hostname}
                    <ExternalLink size={12} />
                  </span>
                  <strong>{source.title}</strong>
                </a>
              ))}
            </div>
          </>
        ) : (
          <p>No usable sources were returned. Try a more specific query.</p>
        )}
        {result.partial && (
          <p className="muted">
            Some search engines did not respond. Sources shown are the results
            actually retrieved.
          </p>
        )}
      </section>
    </details>
  );
}
