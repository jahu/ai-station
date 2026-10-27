import { Link } from "react-router-dom";
import { ArrowUpRight, Download, FileCode, Table2 } from "lucide-react";
import type { Run } from "../api";
import { Badge } from "../components/common";
import { Button } from "../components/ui/button";

type Result = {
  operation?: "create";
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

function ResultTable({ result }: { result: Result }) {
  return (
    <div className="data-preview-table">
      <table>
        <caption className="sr-only">
          {result.operation === "create" ? "Created data" : "Analysis results"}
        </caption>
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
  );
}

export default function AgentDataResult({
  runs,
  taskStatus,
  taskSteps,
}: {
  runs: Run[];
  taskStatus?: string;
  taskSteps?: {
    id: string;
    status: string;
    error_message?: string;
    superseded?: boolean;
    capability?: string;
  }[];
}) {
  const task = runs[0]?.task_id;
  const current = runs.filter((run) => run.task_id === task);
  const resultRun = current.find(
    (run) =>
      run.executor_type === "agent_data_result" &&
      run.status === "succeeded" &&
      run.metadata?.data_result,
  );
  const result = resultRun?.metadata?.data_result as Result | undefined;
  const creating =
    result?.operation === "create" ||
    current.some((run) => {
      const p = run.parameters as {
        data?: { operation?: string };
        definition?: { data?: { operation?: string } };
        agent_data?: { definition?: { data?: { operation?: string } } };
      };
      return (
        p?.data?.operation === "create" ||
        p?.definition?.data?.operation === "create" ||
        p?.agent_data?.definition?.data?.operation === "create"
      );
    });
  const chart = result?.exports?.find((file) => file.mime_type === "image/png");
  const latest = current[0];
  if (!latest) return null;
  const taskStopped =
    !!taskStatus && ["failed", "canceled", "interrupted"].includes(taskStatus);
  const missingResult = !result && taskStatus === "succeeded";
  const status = result
    ? "succeeded"
    : missingResult
      ? "unavailable"
      : taskStopped
        ? taskStatus!
        : latest.status === "succeeded"
          ? "preparing"
          : latest.status;
  const failedSteps = taskStopped
    ? taskSteps?.filter(
        (step) => !step.superseded && step.status === taskStatus,
      )
    : undefined;
  const failedStep =
    failedSteps?.find((step) => !current.some((run) => run.id === step.id)) ??
    failedSteps?.[0];
  const stopped =
    missingResult || ["failed", "canceled", "interrupted"].includes(status);
  const rawError = failedStep?.error_message || latest.error_message;
  const error =
    rawError && rawError.length <= 400 && !rawError.includes("\n")
      ? rawError
      : undefined;
  const detailsId = failedStep?.id ?? latest.id;
  const operation = creating ? "File creation" : "Analysis";
  const terminalMessage = {
    failed: `${operation} failed. Open execution details to inspect the error.`,
    canceled: `${operation} stopped. No new result was published.`,
    interrupted: `${operation} was interrupted. Inspect execution before retrying.`,
    unavailable: `${operation} finished without a verified result. Open execution details.`,
  }[status];
  return (
    <section
      className="agent-data-result"
      aria-label={creating ? "File creation result" : "Data analysis result"}
    >
      <div className="row spread">
        <h3>
          <Table2 size={17} />{" "}
          {creating
            ? result
              ? "Created files"
              : "File creation"
            : "Data analysis"}
        </h3>
        <Badge status={status} />
      </div>
      {result && resultRun ? (
        <>
          <p className="agent-data-answer">{result.answer}</p>
          {chart && (
            <figure className="agent-data-chart">
              <a
                href={`/api/artifacts/${chart.artifact_id}/file`}
                target="_blank"
                rel="noreferrer"
                aria-label="Open analysis chart at full size"
              >
                <img
                  src={`/api/artifacts/${chart.artifact_id}/file`}
                  alt={
                    creating
                      ? "Chart created from instructions"
                      : "Chart generated from the analyzed data"
                  }
                  loading="lazy"
                />
              </a>
              <figcaption>Chart · Select to open full size</figcaption>
            </figure>
          )}
          {result.columns.length > 0 &&
            (chart ? (
              <details>
                <summary>View result table</summary>
                <ResultTable result={result} />
              </details>
            ) : (
              <ResultTable result={result} />
            ))}
          <p className="muted">
            Preview shows up to 20 rows. Download the full result below.
            {result.attempt > 0
              ? ` Code corrected after ${result.attempt} attempt(s).`
              : ""}
          </p>
          <div className="row agent-data-actions">
            {result.exports?.map((file) => (
              <span className="agent-data-file-action" key={file.artifact_id}>
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
                  title={`Inspect ${file.label} in Library`}
                >
                  <ArrowUpRight size={17} />
                </Link>
              </span>
            ))}
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
            {typeof resultRun.metadata?.memory_entry_id === "string" && (
              <Link
                to={`/memory/${resultRun.metadata.memory_entry_id}`}
                className="text-link"
              >
                View saved result memory
              </Link>
            )}
            <Link to={`/runs/${resultRun.id}`} className="text-link">
              Execution details
            </Link>
          </div>
        </>
      ) : (
        <>
          <p className={error || stopped ? "notice" : "muted"}>
            {error ||
              (status === "failed" && failedStep?.capability === "runtime.load"
                ? "The local model could not start. Open execution details."
                : undefined) ||
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
          <Link to={`/runs/${detailsId}`} className="text-link">
            {stopped ? "Execution details" : "View progress and Stop"}
          </Link>
        </>
      )}
    </section>
  );
}
