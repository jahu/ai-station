import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import AgentCodeResearch from "./AgentCodeResearch";
import { activationBlock, localResearchScope } from "./agentActivation";

afterEach(cleanup);
function rows(
  entries: unknown[] = [
    {
      id: "entry",
      content: "Observed values 12 and 15",
      updated_at: "2026-10-24T12:00:00Z",
      source_run_id: "prior-result",
    },
  ],
) {
  const shared = {
    task_id: "task",
    agent_id: "agent",
    project_id: "project",
    parent_run_id: "root",
    status: "succeeded",
  };
  return [
    {
      ...shared,
      id: "handoff",
      executor_type: "agent_page_coding",
      parameters: { source_run_ids: ["memory", "connected"] },
    },
    {
      ...shared,
      id: "memory",
      executor_type: "agent_tool",
      parameters: { tool: "memory_search" },
      metadata: { observation: { scope: "agent", scope_id: "agent", entries } },
    },
    {
      ...shared,
      id: "connected",
      executor_type: "agent_tool",
      parameters: { tool: "http_connector" },
      metadata: {
        http_connector: {
          urls: ["https://data.example.com/"],
          fetched_at: "2026-10-24T12:00:00Z",
          pages: [
            {
              url: "https://data.example.com/",
              status: 200,
              text: "API capture",
            },
          ],
        },
      },
    },
  ] as unknown as Run[];
}
it("shows captured own memory, recorded versions, origin and API sources in the task", () => {
  render(
    <MemoryRouter>
      <AgentCodeResearch runs={rows()} taskId="task" />
    </MemoryRouter>,
  );
  const context = screen.getByLabelText("Context for this task");
  fireEvent.click(context.querySelector("summary")!);
  expect(screen.getByText("Observed values 12 and 15")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Inspect memory" }).getAttribute("href"),
  ).toBe("/memory/entry");
  expect(
    screen.getByRole("link", { name: "Original result" }).getAttribute("href"),
  ).toBe("/runs/prior-result");
  expect(
    screen
      .getByRole("link", { name: "Inspect memory capture" })
      .getAttribute("href"),
  ).toBe("/runs/memory");
  expect(screen.getByText(/This agent's memory/).textContent).toContain(
    "1 saved observation",
  );
});
it("shows an empty captured scope honestly and excludes foreign task observations", () => {
  const values = rows([]);
  values[2].task_id = "foreign";
  render(
    <MemoryRouter>
      <AgentCodeResearch runs={values} taskId="task" />
    </MemoryRouter>,
  );
  fireEvent.click(
    screen.getByLabelText("Context for this task").querySelector("summary")!,
  );
  expect(
    screen.getByText("No enabled observations were available in this scope."),
  ).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Inspect memory" })).toBeNull();
  expect(screen.queryByText("API capture")).toBeNull();
});
it("permits scoped memory and explicit data retention without granting external coding access", () => {
  expect(
    localResearchScope(["python_data", "memory_search", "remember_report"]),
  ).toBe(true);
  expect(localResearchScope(["coding_local", "project_memory"])).toBe(true);
  expect(localResearchScope(["coding_local", "remember_report"])).toBe(false);
  expect(localResearchScope(["coding_cursor", "memory_search"])).toBe(false);
  const tools = ["python_data", "memory_search", "remember_report"].map(
    (name) => ({
      name,
      description: "",
      operational: true,
      required_permissions: [],
    }),
  );
  expect(
    activationBlock(
      {
        enabled: false,
        tools: tools.map((t) => t.name),
        model: "auto",
        data: { input_artifact_ids: [], max_repairs: 1 },
        data_readiness: { ready: true, reason: "" },
      },
      tools,
    ).blocked,
  ).toBe(false);
});
