import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

type Sheet = {
  name: string;
  row_count: number;
  column_count: number;
  formula_count: number;
  preview: string[][];
  preview_row_numbers?: number[];
};
type Preview = { sheets: Sheet[]; note?: string };

export default function DataPreview({ artifact }: { artifact: Artifact }) {
  const [selectedRun, setSelectedRun] = useState("");
  const [sheetIndex, setSheetIndex] = useState(0);
  const runId = selectedRun || artifact.metadata.data_inspection_run_id;
  const run = useQuery({
    queryKey: ["data-inspection", runId],
    enabled: !!runId,
    queryFn: () => api<Run>(`/runs/${runId}`),
    refetchInterval: (query) =>
      ["succeeded", "failed", "canceled", "interrupted"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 1000,
  });
  const inspect = useMutation({
    mutationFn: () =>
      api<Run>("/data/inspections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_id: artifact.id }),
      }),
    onSuccess: (value) => setSelectedRun(value.id),
  });
  const report = run.data?.metadata?.data_preview as Preview | undefined;
  const sheet = report?.sheets[sheetIndex] ?? report?.sheets[0];
  const busy =
    inspect.isPending ||
    (!!runId &&
      !["succeeded", "failed", "canceled", "interrupted"].includes(
        run.data?.status ?? "",
      ));
  return (
    <section className="data-preview" aria-label="Data preview">
      <div className="row spread">
        <h2>Data preview</h2>
        {run.data && (
          <Link to={`/runs/${run.data.id}`}>
            <Badge status={run.data.status} />
          </Link>
        )}
      </div>
      <p className="muted">
        Your original file stays unchanged. Preview shows up to 20 rows and 20
        columns; formulas are never evaluated.
      </p>
      <ErrorNotice error={run.error ?? inspect.error} />
      {run.data?.error_message && (
        <p className="notice">{run.data.error_message}</p>
      )}
      {busy && <p role="status">Reading data locally…</p>}
      {report && sheet && (
        <>
          {report.sheets.length > 1 && (
            <label>
              Sheet
              <select
                value={sheetIndex}
                onChange={(event) => setSheetIndex(Number(event.target.value))}
              >
                {report.sheets.map((item, index) => (
                  <option key={index} value={index}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <p>
            <strong>{sheet.name}</strong> · {sheet.row_count.toLocaleString()}{" "}
            rows · {sheet.column_count} columns
            {sheet.formula_count
              ? ` · ${sheet.formula_count} formulas skipped`
              : ""}
          </p>
          {sheet.preview.length ? (
            <div className="data-preview-table">
              <table>
                <caption className="sr-only">{sheet.name} data preview</caption>
                <thead>
                  <tr>
                    <th scope="col">Row</th>
                    {Array.from(
                      { length: Math.min(sheet.column_count, 20) },
                      (_, index) => (
                        <th scope="col" key={index}>
                          {index + 1}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {sheet.preview.map((row, index) => (
                    <tr key={index}>
                      <th scope="row">
                        {sheet.preview_row_numbers?.[index] ?? index + 1}
                      </th>
                      {Array.from(
                        { length: Math.min(sheet.column_count, 20) },
                        (_, col) => (
                          <td key={col}>{row[col] ?? ""}</td>
                        ),
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No data rows in this sheet.</p>
          )}
          {report.note && <p className="muted">{report.note}</p>}
        </>
      )}
      {!busy && !artifact.trashed_at && (
        <Button variant="secondary" onClick={() => inspect.mutate()}>
          {report ? "Refresh preview" : "Inspect data"}
        </Button>
      )}
      {run.data && (
        <Link className="text-link" to={`/runs/${run.data.id}`}>
          Inspect preview Run
        </Link>
      )}
    </section>
  );
}
