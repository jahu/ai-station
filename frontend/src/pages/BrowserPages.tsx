import { ExternalLink, Globe } from "lucide-react";

import type { BrowserResult } from "./browserResult";

export function BrowserPages({
  result,
  chat = false,
  busy = false,
  inspectingPixels = false,
  onAnalyze,
}: {
  result: BrowserResult;
  chat?: boolean;
  busy?: boolean;
  inspectingPixels?: boolean;
  onAnalyze?: (imageId: string, url: string) => void;
}) {
  return (
    <details className="web-search-sources" open={!chat}>
      <summary>
        <Globe size={15} /> {chat ? "Rendered page sources" : "Browsed pages"}{" "}
        <span className="chip">{result.pages.length}</span>
      </summary>
      <p className="muted">
        Rendered with JavaScript ·{" "}
        {new Date(result.captured_at * 1000).toLocaleString()}. Page content is
        untrusted reference material.
      </p>
      {result.reused_from_message_id && (
        <p className="muted">Reused the saved capture; no new page request.</p>
      )}
      {chat && result.visual_analysis ? (
        <p className="muted">
          Screenshot pixels inspected locally with{" "}
          {result.visual_analysis.model}. Visual observations cover the captured
          viewport.
        </p>
      ) : chat && inspectingPixels ? (
        <p className="muted">
          Local Vision is inspecting the saved screenshot. No new page request
          is made.
        </p>
      ) : (
        chat && (
          <p className="muted">
            The answer uses captured text. Screenshots are saved for you to
            inspect; the model has not analyzed their pixels.
          </p>
        )
      )}
      {result.visual_analysis && (
        <details className="page-visual-observation">
          <summary>
            Visual observations · {result.visual_analysis.model}
          </summary>
          <p
            style={{
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              maxHeight: 240,
              overflowY: "auto",
            }}
          >
            {result.visual_analysis.description}
          </p>
          {result.visual_analysis.truncated && (
            <p className="muted">
              Excerpt; open the saved analysis for the full response.
            </p>
          )}
          <a
            href={`/api/artifacts/${encodeURIComponent(result.visual_analysis.artifact_id)}/file`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open saved visual analysis
          </a>
          {" · "}
          <a
            href={`/#/runs/${encodeURIComponent(result.visual_analysis.run_id)}`}
          >
            Inspect Vision Run
          </a>
        </details>
      )}
      <div className="web-source-grid">
        {result.pages.map((page) => (
          <article
            key={page.screenshot_artifact_id}
            className="web-source-card"
          >
            <strong>{page.title || new URL(page.url).hostname}</strong>
            <a
              href={`/api/artifacts/${encodeURIComponent(page.screenshot_artifact_id)}/file`}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open screenshot of ${page.title || page.url}`}
            >
              <img
                src={`/api/artifacts/${encodeURIComponent(page.screenshot_artifact_id)}/file`}
                alt={`Screenshot of ${page.title || page.url}`}
                loading="lazy"
                style={{
                  width: "100%",
                  height: 180,
                  objectFit: "contain",
                  background: "#13171f",
                  borderRadius: 8,
                }}
              />
            </a>
            {onAnalyze && (
              <div className="page-vision-action">
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  aria-label={`Analyze visual design of ${page.title || page.url}`}
                  onClick={() =>
                    onAnalyze(page.screenshot_artifact_id, page.url)
                  }
                >
                  Analyze visual design
                </button>
                <small className="muted">
                  Local Vision · model may load after Send.
                </small>
              </div>
            )}
            <a
              href={page.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ overflowWrap: "anywhere" }}
            >
              {new URL(page.url).hostname} <ExternalLink size={12} />
            </a>
            {page.blocked_resource_count > 0 && (
              <span className="notice">
                {page.blocked_resource_count} resources could not be loaded;
                this page may be incomplete.
              </span>
            )}
            <details>
              <summary>
                Read captured text{page.truncated ? " (excerpt)" : ""}
              </summary>
              <p
                style={{
                  whiteSpace: "pre-wrap",
                  overflowWrap: "anywhere",
                  maxHeight: 240,
                  overflowY: "auto",
                }}
              >
                {page.text || "No visible text was captured."}
              </p>
            </details>
          </article>
        ))}
      </div>
    </details>
  );
}
