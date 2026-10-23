import { Link } from "react-router-dom";
import { Download, FileCode, Table2 } from "lucide-react";
import type { Run } from "../api";
import { Badge } from "../components/common";
import { Button } from "../components/ui/button";

type Result = {
  answer: string;
  columns: string[];
  rows: string[][];
  download_artifact_id: string;
  script_artifact_id: string;
  input_artifact_ids: string[];
  attempt: number;
  exports?: {
    artifact_id: string;
    filename: string;
    label: string;
    mime_type: string;
  }[];
};
export default function AgentDataResult({ runs }: { runs: Run[] }) {
  const task = runs[0]?.task_id;
  const current = runs.filter((run) => run.task_id === task);
  const resultRun = current.find(
    (run) =>
      run.executor_type === "agent_data_result" &&
      run.status === "succeeded" &&
      run.metadata?.data_result,
  );
  const result = resultRun?.metadata?.data_result as Result | undefined;
  const latest = current[0];
  if (!latest) return null;
  const stopped = ["failed", "canceled", "interrupted"].includes(latest.status);
  const terminalMessage = {
    failed: "Analysis failed. Open execution details to inspect the error.",
    canceled: "Analysis stopped. No new result was published.",
    interrupted: "Analysis was interrupted. Inspect execution before retrying.",
  }[latest.status];
  return (
    <section className="agent-data-result" aria-label="Data analysis result">
      <div className="row spread">
        <h3>
          <Table2 size={17} /> Data analysis
        </h3>
        <Badge status={result ? "succeeded" : latest.status} />
      </div>
      {result && resultRun ? (
        <>
          <p className="agent-data-answer">{result.answer}</p>
          {result.exports?.map((file) => (
            <div className="agent-data-export" key={file.artifact_id}>
              {file.mime_type === "image/png" && (
                <figure>
                  <a
                    href={`/api/artifacts/${file.artifact_id}/file`}
                    target="_blank"
                    rel="noreferrer"
                    aria-label="Open analysis chart at full size"
                  >
                    <img
                      src={`/api/artifacts/${file.artifact_id}/file`}
                      alt="Chart generated from the analyzed data"
                      loading="lazy"
                    />
                  </a>
                  <figcaption>{file.label}</figcaption>
                </figure>
              )}
              <div className="row agent-data-actions">
                <Button asChild variant="secondary">
                  <a
                    href={`/api/artifacts/${file.artifact_id}/file`}
                    download={file.filename}
                  >
                    <Download size={15} /> Download {file.label}
                  </a>
                </Button>
                <Link
                  to={`/library/${file.artifact_id}`}
                  className="text-link"
                  aria-label={`Inspect ${file.label} in Library`}
                >
                  Inspect in Library
                </Link>
              </div>
            </div>
          ))}
          {result.columns.length > 0 && (
            <div className="data-preview-table">
              <table>
                <caption className="sr-only">Analysis results</caption>
                <thead>
                  <tr>
                    {result.columns.map((column, index) => (
                      <th key={index} scope="col">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, index) => (
                    <tr key={index}>
                      {row.map((cell, col) => (
                        <td key={col}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">
            Preview shows up to 20 rows. Download the full result below.
            {result.attempt > 0
              ? ` Code corrected after ${result.attempt} attempt(s).`
              : ""}
          </p>
          <div className="row agent-data-actions">
            <Button asChild variant="secondary">
              <a
                href={`/api/artifacts/${result.download_artifact_id}/file`}
                download="result.csv"
              >
                <Download size={15} /> Download CSV
              </a>
            </Button>
            <Link
              to={`/library/${result.script_artifact_id}`}
              className="text-link"
            >
              <FileCode size={15} /> View Python source
            </Link>
            <Link to={`/runs/${resultRun.id}`} className="text-link">
              Execution details
            </Link>
          </div>
        </>
      ) : (
        <>
          <p className={latest.error_message ? "notice" : "muted"}>
            {latest.error_message ||
              terminalMessage ||
              ({
                agent_data_generate:
                  "Writing the analysis with your local model…",
                python: "Running Python locally…",
                agent_data_result: "Checking the result…",
                project_setup: "Creating a private workspace…",
                worktree_prepare: "Preparing the analysis workspace…",
              }[latest.executor_type] ??
                "Preparing data analysis…")}
          </p>
          <Link to={`/runs/${latest.id}`} className="text-link">
            {stopped ? "Execution details" : "View progress and Stop"}
          </Link>
        </>
      )}
    </section>
  );
}
