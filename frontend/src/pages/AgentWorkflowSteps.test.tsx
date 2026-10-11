import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import { AgentLastWorkflowSteps } from "./AgentWorkflowSteps";

afterEach(() => cleanup());

const lastParent: Run = {
  id: "flow-run",
  capability: "agent.workflow",
  executor_type: "agent_workflow",
  execution_target: "container",
  status: "succeeded",
  created_at: "2026-10-11T12:00:00Z",
  workflow: {
    parent_run_id: "flow-run",
    mode: "sequential",
    tool_calling: "bounded",
    steps: [
      {
        run_id: "step-search",
        key: "memory_search",
        gate: "none",
        status: "succeeded",
        capability: "agent.step",
      },
      {
        run_id: "step-report",
        key: "report",
        gate: "none",
        status: "succeeded",
        capability: "agent.execute",
        tool_calls: [
          {
            id: "call-0-0",
            tool: "system_snapshot",
            arguments: {},
            round: 0,
          },
        ],
      },
    ],
  },
} as Run;

const olderParent: Run = {
  id: "old-flow",
  capability: "agent.workflow",
  executor_type: "agent_workflow",
  execution_target: "container",
  status: "succeeded",
  created_at: "2026-10-10T12:00:00Z",
  workflow: {
    parent_run_id: "old-flow",
    mode: "gated",
    steps: [
      {
        run_id: "old-step",
        key: "system_snapshot",
        gate: "none",
        status: "succeeded",
        capability: "agent.step",
      },
    ],
  },
} as Run;

it("shows last-parent steps without inventing a Run now control", () => {
  render(
    <MemoryRouter>
      <AgentLastWorkflowSteps runs={[lastParent, olderParent]} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("heading", { name: "Workflow steps" })).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect step memory_search step-sea" })
      .getAttribute("href"),
  ).toBe("/runs/step-search");
  expect(
    screen
      .getByRole("link", { name: "Inspect step report step-rep" })
      .getAttribute("href"),
  ).toBe("/runs/step-report");
  expect(screen.queryByRole("link", { name: /system_snapshot/ })).toBeNull();
  expect(screen.getByText("1 registry call")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Run now/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Cancel/ })).toBeNull();
  expect(
    screen.getByRole("region", { name: "Workflow steps" }).textContent,
  ).toMatch(/Stop stays on execution history/);
});

it("moves through last-parent workflow steps with arrow keys", () => {
  render(
    <MemoryRouter>
      <AgentLastWorkflowSteps runs={[lastParent]} />
    </MemoryRouter>,
  );
  const first = screen.getByRole("link", {
    name: "Inspect step memory_search step-sea",
  });
  const second = screen.getByRole("link", {
    name: "Inspect step report step-rep",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Workflow steps" })).toBeTruthy();
  expect(
    screen.getByRole("region", { name: "Workflow steps" }).textContent,
  ).toMatch(/Stop stays on execution history/);
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
