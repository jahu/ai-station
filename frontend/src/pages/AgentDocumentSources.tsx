import { Link } from "react-router-dom";
import { documentObservation } from "./document-context";
import "./AgentMemorySources.css";
import "./AgentDocumentSources.css";

export default function AgentDocumentSources({
  captures,
}: {
  captures: { result: unknown; runId?: string }[];
}) {
  return (
    <>
      {captures.map(({ result, runId }) => {
        if (!documentObservation(result)) return null;
        return (
          <section
            className="web-search-sources agent-document-sources"
            key={result.artifact_id}
            aria-label="Captured document sources"
          >
            <h4>Selected documents</h4>
            <p className="muted">
              Text captured for this task. Source files stay unchanged. Later
              edits do not rewrite this capture.
            </p>
            {result.query && (
              <p className="muted">Document search: {result.query}</p>
            )}
            {!!result.offset && (
              <p className="muted">Text window from offset {result.offset}</p>
            )}
            <ul className="source-list">
              {result.documents.map((doc) => (
                <li key={doc.source_artifact_id}>
                  <strong>{doc.name}</strong>
                  <p className="muted">
                    {doc.mime_type === "application/pdf"
                      ? `${doc.page_count} page${doc.page_count === 1 ? "" : "s"}`
                      : "Text document"}
                    {doc.truncated ? " · Extraction limit reached" : ""}
                    {doc.excerpted
                      ? " · Model received an excerpt"
                      : " · Captured text supplied"}
                  </p>
                  {doc.query_found === false && (
                    <p className="muted">No matching text in this capture.</p>
                  )}
                  <p className="agent-document-preview">
                    {doc.text.slice(0, 300)}
                    {doc.text.length > 300 ? "…" : ""}
                  </p>
                  <details className="agent-memory-capture">
                    <summary>Text supplied to the model</summary>
                    <pre>{doc.text}</pre>
                  </details>
                  <div className="row">
                    <Link
                      className="text-link"
                      to={`/library/${encodeURIComponent(doc.source_artifact_id)}`}
                    >
                      Original document
                    </Link>
                    <Link
                      className="text-link"
                      to={`/library/${encodeURIComponent(doc.text_artifact_id)}`}
                    >
                      Full captured text
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
            <p className="muted">
              Captured {new Date(result.captured_at).toLocaleString()}
            </p>
            <div className="row">
              <Link
                className="text-link"
                to={`/library/${encodeURIComponent(result.artifact_id)}`}
              >
                Inspect document capture
              </Link>
              {runId && (
                <Link
                  className="text-link"
                  to={`/runs/${encodeURIComponent(runId)}`}
                >
                  Document reading Run
                </Link>
              )}
            </div>
          </section>
        );
      })}
    </>
  );
}
