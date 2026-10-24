import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DataAgentDraftSource from "./DataAgentDraftSource";

afterEach(cleanup);
const source = {
  source_run_id: "original-analysis",
  definition: {
    goal: "Compare the selected values",
    tools: ["python_data", "read_documents", "http_fetch"],
  },
  input_names: ["sales.csv"],
  documents: ["contract.pdf"],
  live_public_sources: true,
};
it("shows the retained task, files, tools and live-source behavior with a source link", () => {
  render(
    <MemoryRouter>
      <DataAgentDraftSource value={source} />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("region", { name: "Original analysis for this agent" }),
  ).toBeTruthy();
  expect(screen.getByText("Compare the selected values")).toBeTruthy();
  expect(
    screen.getByText("Selected files: sales.csv, contract.pdf"),
  ).toBeTruthy();
  expect(screen.getByText(/retained live public sources/)).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect original analysis" })
      .getAttribute("href"),
  ).toBe("/runs/original-analysis");
  expect(
    screen.getByText(/Review the schedule and enable it when ready/),
  ).toBeTruthy();
});
it("distinguishes immutable captures and collapses a long original instruction", () => {
  render(
    <MemoryRouter>
      <DataAgentDraftSource
        value={{
          ...source,
          live_public_sources: false,
          definition: { ...source.definition, goal: "word ".repeat(300) },
        }}
      />
    </MemoryRouter>,
  );
  expect(
    screen.getByText(/retained selected saved files or captured data/),
  ).toBeTruthy();
  expect(screen.getByText("Original analysis instruction")).toBeTruthy();
  expect(
    screen.getByText("Original analysis instruction").closest("details")?.open,
  ).toBe(false);
  expect(screen.queryByText(/retained live public sources/)).toBeNull();
});
it("does not turn incomplete or invented metadata into a source claim", () => {
  render(
    <MemoryRouter>
      <DataAgentDraftSource
        value={{
          source_run_id: "wrong",
          definition: { goal: "bad", tools: [4] },
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("region")).toBeNull();
});

it("identifies current selected inputs as a creation request, without claiming a previous analysis", () => {
  render(
    <MemoryRouter>
      <DataAgentDraftSource value={{ ...source, kind: "selected_inputs" }} />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("region", { name: "Selected inputs for this agent" }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect agent creation" })
      .getAttribute("href"),
  ).toBe("/runs/original-analysis");
  expect(screen.queryByText("Drafted from this analysis")).toBeNull();
  expect(
    screen.getByText(/Saved creation request and input selection/),
  ).toBeTruthy();
});

it.each([
  ["report", "Report"],
  ["code", "Local code"],
  ["data", "Data analysis"],
])(
  "labels the reviewed %s recipe without claiming an executed workspace",
  (family, label) => {
    render(
      <MemoryRouter>
        <DataAgentDraftSource
          value={{ ...source, kind: "selected_inputs" }}
          family={family}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByText(
        `Prepared agent: ${label}. Review its task and tools below.`,
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Selected readers: Documents, Public pages"),
    ).toBeTruthy();
    expect(screen.queryByText(/Retained tools:/)).toBeNull();
    expect(
      screen.getByText(/reports read only the reviewed sources/),
    ).toBeTruthy();
  },
);
