import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AgentControlRun from "./AgentControlRun";

afterEach(cleanup);
it("links the exact execution with its current state", () => {
  const { rerender } = render(
    <MemoryRouter>
      <AgentControlRun run={{ id: "original-run", status: "queued" }} />
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
        run={{ id: "original-run", status: "succeeded" }}
        tabIndex={-1}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("succeeded")).toBeTruthy();
  expect(screen.getByRole("link").tabIndex).toBe(-1);
});
it("does not claim Stop has already killed a process", () => {
  render(
    <MemoryRouter>
      <AgentControlRun run={{ id: "held", status: "cancel_requested" }} />
    </MemoryRouter>,
  );
  expect(screen.getByText(/waiting for owned work/)).toBeTruthy();
  expect(screen.queryByText("canceled")).toBeNull();
});
it("shows when the normal approval still needs review", () => {
  render(
    <MemoryRouter>
      <AgentControlRun run={{ id: "review", status: "waiting_for_approval" }} />
    </MemoryRouter>,
  );
  expect(screen.getByText(/Review the requested approval/)).toBeTruthy();
});
