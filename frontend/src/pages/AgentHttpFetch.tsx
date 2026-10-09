import { useId } from "react";
import { ExternalLink, Globe } from "lucide-react";
import { useListKeyboard } from "./useListKeyboard";

export type FetchedPage = {
  url: string;
  status?: number;
  content_type?: string;
  text?: string;
  truncated?: boolean;
  skipped?: string;
  error?: string;
  untrusted?: boolean;
};

export type FetchResult = {
  urls: string[];
  fetched_at: string;
  pages: FetchedPage[];
};

export function FetchedPages({ result }: { result: FetchResult }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    result.pages,
    (page) => page.url,
  );
  return (
    <details className="web-search-sources" open>
      <summary>
        <Globe size={15} /> Fetched pages{" "}
        <span className="chip">{result.pages.length}</span>
      </summary>
      <section aria-labelledby={headingId}>
        <h3 id={headingId} className="sr-only">
          Fetched pages
        </h3>
        <p className="muted">
          Reviewed GET ·{" "}
          <time dateTime={result.fetched_at}>
            {new Date(result.fetched_at).toLocaleString()}
          </time>
          . Excerpts are untrusted; JavaScript was not executed.
        </p>
        {result.pages.length ? (
          <>
            <p id={labelId} className="dashboard-note">
              Arrow keys choose a page while the list is focused. Enter opens
              the selected public URL. JavaScript was not executed.
            </p>
            <div
              ref={listRef}
              className="web-source-grid"
              aria-labelledby={labelId}
              onKeyDown={onKeyDown}
            >
              {result.pages.map((page, i) => (
                <a
                  key={page.url}
                  href={page.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="web-source-card"
                  aria-label={`Page ${page.url}`}
                  {...itemProps(i, page.url)}
                >
                  <span className="muted">
                    {page.status ?? "—"} · {hostname(page.url)}
                    <ExternalLink size={12} />
                  </span>
                  <strong>{page.url}</strong>
                  <span className="muted">{pageLabel(page)}</span>
                </a>
              ))}
            </div>
          </>
        ) : (
          <p>No pages were fetched.</p>
        )}
      </section>
    </details>
  );
}

function hostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function pageLabel(page: FetchedPage) {
  if (page.error) return page.error;
  if (page.skipped) return `${page.skipped} skipped`;
  if (page.truncated) return "Text truncated";
  if (page.text) return "HTML/text excerpt stored";
  return "No visible text";
}
