import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AgentControlRun from "./AgentControlRun";

afterEach(cleanup);
it("links the exact execution with its current state", () => {
  const { rerender } = render(
    <MemoryRouter>
      <AgentControlRun
        result={{ agent_id: "agent-one", outcome: "queued" }}
        run={{ id: "original-run", status: "queued" }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("queued")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect agent execution" })
      .getAttribute("href"),
  ).toBe("/runs/original-run");
  rerender(
    <MemoryRouter>
      <AgentControlRun
        result={{ agent_id: "agent-one", outcome: "queued" }}
        run={{ id: "original-run", status: "succeeded" }}
        tabIndex={-1}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("succeeded")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Inspect agent execution" }).tabIndex,
  ).toBe(-1);
});
it("does not claim Stop has already killed a process", () => {
  render(
    <MemoryRouter>
      <AgentControlRun
        result={{ agent_id: "agent-one", outcome: "queued" }}
        run={{ id: "held", status: "cancel_requested" }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(/waiting for owned work/)).toBeTruthy();
  expect(screen.queryByText("canceled")).toBeNull();
});
it("shows when the normal approval still needs review", () => {
  render(
    <MemoryRouter>
      <AgentControlRun
        result={{ agent_id: "agent-one", outcome: "queued" }}
        run={{ id: "review", status: "waiting_for_approval" }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(/Review the requested approval/)).toBeTruthy();
});
it("offers explicit review for a disabled definition without inventing an execution", () => {
  render(
    <MemoryRouter>
      <AgentControlRun
        result={{ agent_id: "disabled-agent", outcome: "needs_review" }}
      />
    </MemoryRouter>,
  );
  expect(
    screen
      .getByRole("link", { name: "Review & enable agent" })
      .getAttribute("href"),
  ).toBe("/agents/disabled-agent?view=settings");
  expect(
    screen.queryByRole("link", { name: "Inspect agent execution" }),
  ).toBeNull();
});

it("separates a ready result from pending email review", () => {
  render(
    <MemoryRouter>
      <AgentControlRun
        result={{ agent_id: "agent-one", outcome: "queued" }}
        run={{
          id: "workflow",
          status: "succeeded",
          delivery_status: "waiting_for_approval",
          delivery_run_id: "email-one",
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("succeeded")).toBeTruthy();
  expect(screen.getByText(/Email delivery: waiting for approval/)).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Inspect delivery" }).getAttribute("href"),
  ).toBe("/runs/email-one");
});
