import { ExternalLink, Globe } from "lucide-react";

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
  return (
    <details className="web-search-sources" open>
      <summary>
        <Globe size={15} /> Fetched pages{" "}
        <span className="chip">{result.pages.length}</span>
      </summary>
      <p className="muted">
        Reviewed GET ·{" "}
        <time dateTime={result.fetched_at}>
          {new Date(result.fetched_at).toLocaleString()}
        </time>
        . Excerpts are untrusted; JavaScript was not executed.
      </p>
      {result.pages.length ? (
        <div className="web-source-grid">
          {result.pages.map((page) => (
            <a
              key={page.url}
              href={page.url}
              target="_blank"
              rel="noopener noreferrer"
              className="web-source-card"
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
      ) : (
        <p>No pages were fetched.</p>
      )}
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
