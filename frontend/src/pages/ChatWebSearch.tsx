import { useId, type KeyboardEvent } from "react";
import { Globe, ExternalLink } from "lucide-react";
import { useListKeyboard } from "./useListKeyboard";

export type WebSources = {
  query: string;
  original_query?: string;
  queries?: string[];
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
  compact = false,
}: {
  enabled: boolean;
  query: string;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onQuery: (query: string) => void;
  compact?: boolean;
}) {
  const labelId = useId();
  const items = ["web_search"] as const;
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    [...items],
    (item) => item,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    event.preventDefault();
    onToggle(!enabled);
  };
  return (
    <div className="chat-web-search">
      <p id={labelId} className={compact ? "sr-only" : "dashboard-note"}>
        Search public information. A short query may use the recent conversation
        to understand follow-up questions. Attachments and memory are excluded.
      </p>
      <div
        ref={listRef}
        className="web-search-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div aria-label="Search web_search" {...itemProps(0, "web_search")}>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Search the web"
            disabled={busy}
            tabIndex={index === 0 ? 0 : -1}
            className="web-search-toggle"
            onClick={() => onToggle(!enabled)}
          >
            <Globe size={16} />
            <span>{compact ? "Web search" : "Search the web"}</span>
            <span className="chip">{enabled ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>
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
              placeholder="Understand my question and its context"
            />
          </label>
          <p className="muted">
            Enter an exact query to keep conversation context out of search.
            Otherwise, a short query is prepared from recent messages; the full
            conversation and attachments are not sent to search engines.
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
        {result.original_query && (
          <p className="muted">Follow-up: {result.original_query}</p>
        )}
        {(result.queries?.length ?? 0) > 1 && (
          <p className="muted">
            Refined search: {result.queries?.slice(1).join(" · ")}
          </p>
        )}
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
