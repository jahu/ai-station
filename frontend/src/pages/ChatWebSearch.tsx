import { useId, useState, type KeyboardEvent } from "react";
import { Globe, ExternalLink, SlidersHorizontal } from "lucide-react";
import { useListKeyboard } from "./useListKeyboard";

export type WebSources = {
  query: string;
  original_query?: string;
  queries?: string[];
  query_preparation?: { location: "local" | "external"; model: string };
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
  renderPages = false,
  onRenderPages,
}: {
  enabled: boolean;
  query: string;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onQuery: (query: string) => void;
  compact?: boolean;
  renderPages?: boolean;
  onRenderPages?: (enabled: boolean) => void;
}) {
  const labelId = useId();
  const queryId = useId();
  const [queryOpen, setQueryOpen] = useState(false);
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
        Allow web research when needed and read requested public pages. Visual
        website questions may capture a screenshot and load an installed local
        Vision model. Search may use recent conversation context. Attachments
        and memory are excluded from search.
      </p>
      <div className="web-search-actions">
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
              aria-describedby={labelId}
              title="Web available: search when useful, read public pages and inspect website designs locally"
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
        {compact && enabled && (
          <button
            type="button"
            className="web-search-options"
            aria-label="Search options"
            aria-expanded={queryOpen}
            aria-controls={queryId}
            title="Search options"
            disabled={busy}
            onClick={() => setQueryOpen(!queryOpen)}
          >
            <SlidersHorizontal size={15} />
          </button>
        )}
      </div>
      {enabled && (!compact || queryOpen) && (
        <div className="web-search-query" id={queryId}>
          <label>
            Search query <span className="muted">optional</span>
            <input
              aria-label="Search query"
              maxLength={500}
              value={query}
              disabled={busy}
              onChange={(e) => {
                onQuery(e.target.value);
                if (e.target.value.trim()) onRenderPages?.(false);
              }}
              placeholder="Understand my question and its context"
            />
          </label>
          <p className="muted">
            Enter an exact query to request a search without conversation
            context. Otherwise, AI Station decides whether search is useful and
            prepares a short query when needed. The full conversation and
            attachments are not sent to search engines.
          </p>
          {onRenderPages && (
            <>
              <label className="web-render-option">
                <input
                  type="checkbox"
                  checked={renderPages && !query.trim()}
                  disabled={busy || !!query.trim()}
                  onChange={(e) => onRenderPages(e.target.checked)}
                />
                Read JavaScript pages
              </label>
              <p className="muted">
                For this message: include a public page URL. The configured
                Browser executor renders it and saves a screenshot, without
                signing in. Use this for JavaScript-dependent text pages. Visual
                website questions already use local Vision automatically with
                Web on; this option is not required. Use an empty search query
                to enable it.
              </p>
            </>
          )}
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
          <p className="muted">Question: {result.original_query}</p>
        )}
        {result.query_preparation?.location === "local" && (
          <p className="muted">
            Query prepared locally · {result.query_preparation.model}
          </p>
        )}
        {result.query_preparation?.location === "external" && (
          <p className="muted">
            Query prepared with selected external model ·{" "}
            {result.query_preparation.model}
          </p>
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
