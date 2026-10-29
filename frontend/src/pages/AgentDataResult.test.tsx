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
        taskStatus="failed"
        taskSteps={[
          {
            id: "notification",
            status: "failed",
            error_message: "Notification failed",
          },
        ]}
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

it.each(["failed", "canceled", "interrupted"])(
  "uses the actual %s task outcome when only successful publication is in data runs",
  (status) => {
    render(
      <MemoryRouter>
        <AgentDataResult
          runs={[
            run({
              id: "publisher",
              executor_type: "agent_workflow",
              status: "succeeded",
            }),
          ]}
          taskStatus={status}
          taskSteps={[
            {
              id: "superseded",
              status,
              superseded: true,
              error_message: "Old error",
            },
            {
              id: "model-load",
              status,
              error_message: status === "failed" ? "GPU out of memory" : "",
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(status)).toBeTruthy();
    expect(screen.queryByText("succeeded")).toBeNull();
    expect(screen.queryByText("Preparing data analysis…")).toBeNull();
    expect(screen.queryByText("Old error")).toBeNull();
    expect(
      screen.queryByRole("link", { name: "View progress and Stop" }),
    ).toBeNull();
    expect(
      screen
        .getByRole("link", { name: "Execution details" })
        .getAttribute("href"),
    ).toBe("/runs/model-load");
    if (status === "failed")
      expect(screen.getByText("GPU out of memory")).toBeTruthy();
  },
);

it("does not equate successful graph publication with a verified result", () => {
  const view = render(
    <MemoryRouter>
      <AgentDataResult
        runs={[run({ status: "succeeded", executor_type: "agent_workflow" })]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("preparing")).toBeTruthy();
  expect(screen.queryByText("succeeded")).toBeNull();
  view.rerender(
    <MemoryRouter>
      <AgentDataResult
        runs={[run({ status: "succeeded" })]}
        taskStatus="succeeded"
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("unavailable")).toBeTruthy();
  expect(
    screen.getByText(
      "Analysis finished without a verified result. Open execution details.",
    ),
  ).toBeTruthy();
  expect(
    screen.queryByRole("link", { name: "View progress and Stop" }),
  ).toBeNull();
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
  expect(
    screen
      .getByText("View result table")
      .closest("details")
      ?.hasAttribute("open"),
  ).toBe(false);
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

const waitingModel = (values: Partial<Run> = {}) =>
  run({
    id: "waiting-model",
    executor_type: "llama_load",
    status: "queued",
    resource_wait: {
      run_id: "waiting-model",
      reason: "gpu",
      checked_at: "2026-10-27T14:00:00Z",
      required_mib: 0,
      available_mib: 24000,
      reserved_mib: 0,
      headroom_mib: 1024,
    },
    ...values,
  });

it("shows the exact queued GPU dependency despite a running graph publisher", () => {
  render(
    <MemoryRouter>
      <AgentDataResult
        taskStatus="queued"
        runs={[
          run({ id: "publisher", executor_type: "agent_workflow" }),
          waitingModel(),
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("queued")).toBeTruthy();
  expect(screen.getByText("Waiting for an available GPU")).toBeTruthy();
  expect(screen.queryByText("Preparing data analysis…")).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "Inspect waiting Run" })
      .getAttribute("href"),
  ).toBe("/runs/waiting-model");
  expect(
    screen
      .getByRole("link", { name: "View progress and Stop" })
      .getAttribute("href"),
  ).toBe("/runs/waiting-model");
});

it("shows reported memory admission and then loading after the wait clears", () => {
  const waiting = waitingModel();
  waiting.resource_wait = {
    ...waiting.resource_wait!,
    reason: "memory",
    required_mib: 12288,
    available_mib: 4096,
  };
  const view = render(
    <MemoryRouter>
      <AgentDataResult runs={[waiting]} />
    </MemoryRouter>,
  );
  expect(screen.getByText("Waiting for memory")).toBeTruthy();
  expect(screen.getByText(/RAM needed: 12.0 GiB/)).toBeTruthy();
  view.rerender(
    <MemoryRouter>
      <AgentDataResult runs={[waitingModel({ status: "running" })]} />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("region", { name: "Resource wait" })).toBeNull();
  expect(screen.getByText("Loading your local model…")).toBeTruthy();
});

it.each(["failed", "canceled", "interrupted", "succeeded", "cancel_requested"])(
  "does not show an automatic retry notice for a %s task",
  (taskStatus) => {
    render(
      <MemoryRouter>
        <AgentDataResult taskStatus={taskStatus} runs={[waitingModel()]} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("region", { name: "Resource wait" })).toBeNull();
  },
);

it.each(["failed", "canceled", "interrupted", "cancel_requested"])(
  "preserves the latest %s agent execution when no aggregate task status is supplied",
  (status) => {
    render(
      <MemoryRouter>
        <AgentDataResult
          runs={[run({ id: "latest", status }), waitingModel()]}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("region", { name: "Resource wait" })).toBeNull();
    expect(screen.getByText(status.replaceAll("_", " "))).toBeTruthy();
    if (status === "cancel_requested") {
      expect(screen.getByText("Analysis is stopping…")).toBeTruthy();
      expect(screen.queryByText("Running Python locally…")).toBeNull();
    }
  },
);

it.each(["other-task", "wrong-run", "stale-status"])(
  "does not adopt a %s resource notice",
  (problem) => {
    const wait = waitingModel();
    if (problem === "other-task") wait.task_id = "other";
    if (problem === "wrong-run") wait.resource_wait!.run_id = "unrelated";
    if (problem === "stale-status") wait.status = "succeeded";
    render(
      <MemoryRouter>
        <AgentDataResult runs={[run({ id: "current" }), wait]} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("region", { name: "Resource wait" })).toBeNull();
    expect(screen.getByText("Running Python locally…")).toBeTruthy();
  },
);
