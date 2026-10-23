import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import AgentDataResult from "./AgentDataResult";

afterEach(cleanup);
const run = (values: Partial<Run>) =>
  ({
    task_id: "current",
    status: "running",
    executor_type: "python",
    ...values,
  }) as Run;
it("shows verified result text, a literal table, download and source", () => {
  render(
    <MemoryRouter>
      <AgentDataResult
        runs={[
          run({
            id: "result-run",
            status: "succeeded",
            executor_type: "agent_data_result",
            metadata: {
              data_result: {
                answer: "Total: 27",
                columns: ["Total"],
                rows: [["27"]],
                download_artifact_id: "csv",
                script_artifact_id: "source",
                attempt: 1,
              },
            },
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("Total: 27")).toBeTruthy();
  expect(screen.getByRole("cell", { name: "27" })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Download CSV" }).getAttribute("href"),
  ).toBe("/api/artifacts/csv/file");
  expect(
    screen
      .getByRole("link", { name: "View Python source" })
      .getAttribute("href"),
  ).toBe("/library/source");
});
it("never presents a prior task's successful answer as current progress", () => {
  render(
    <MemoryRouter>
      <AgentDataResult
        runs={[
          run({ id: "running" }),
          run({
            task_id: "old",
            executor_type: "agent_data_result",
            metadata: { data_result: { answer: "Old answer" } },
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.queryByText("Old answer")).toBeNull();
  expect(screen.getByText("Running Python locally…")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "View progress and Stop" })
      .getAttribute("href"),
  ).toBe("/runs/running");
});
it("preserves failed execution state rather than showing successful preparation", () => {
  render(
    <MemoryRouter>
      <AgentDataResult
        runs={[
          run({
            id: "failed",
            status: "failed",
            error_message: "Analysis output is invalid",
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("Analysis output is invalid")).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Download CSV" })).toBeNull();
});

it("labels canceled analysis without pretending it is still running", () => {
  render(
    <MemoryRouter>
      <AgentDataResult runs={[run({ status: "canceled" })]} />
    </MemoryRouter>,
  );
  expect(
    screen.getByText("Analysis stopped. No new result was published."),
  ).toBeTruthy();
  expect(screen.queryByText("Running Python locally…")).toBeNull();
  expect(screen.getByRole("link", { name: "Execution details" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Download CSV" })).toBeNull();
});

it("shows the verified chart inline with named file downloads and Library links", () => {
  render(
    <MemoryRouter>
      <AgentDataResult
        runs={[
          run({
            id: "result",
            status: "succeeded",
            executor_type: "agent_data_result",
            metadata: {
              data_result: {
                answer: "Wykres i Excel są gotowe.",
                columns: ["Total"],
                rows: [["27"]],
                download_artifact_id: "csv",
                script_artifact_id: "python",
                attempt: 0,
                exports: [
                  {
                    artifact_id: "plot",
                    filename: "chart.png",
                    label: "Chart",
                    mime_type: "image/png",
                  },
                  {
                    artifact_id: "excel",
                    filename: "result.xlsx",
                    label: "Excel workbook",
                    mime_type:
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  },
                  {
                    artifact_id: "report",
                    filename: "report.txt",
                    label: "Text report",
                    mime_type: "text/plain",
                  },
                ],
              },
            },
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(
    screen
      .getByRole("img", { name: "Chart generated from the analyzed data" })
      .getAttribute("src"),
  ).toBe("/api/artifacts/plot/file");
  expect(screen.queryByRole("cell", { name: "27" })).toBeNull();
  expect(screen.getByText("View result table")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Open analysis chart at full size" })
      .getAttribute("target"),
  ).toBe("_blank");
  for (const [label, id, filename] of [
    ["Chart", "plot", "chart.png"],
    ["Excel workbook", "excel", "result.xlsx"],
    ["Text report", "report", "report.txt"],
  ]) {
    const download = screen.getByRole("link", { name: `Download ${label}` });
    expect(download.getAttribute("href")).toBe(`/api/artifacts/${id}/file`);
    expect(download.getAttribute("download")).toBe(filename);
    expect(
      screen
        .getByRole("link", { name: `Inspect ${label} in Library` })
        .getAttribute("href"),
    ).toBe(`/library/${id}`);
  }
});
