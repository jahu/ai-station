import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AgentResultSources from "./AgentResultSources";

afterEach(cleanup);
const source = {
  source_message_id: "source-message",
  workflow_run_id: "workflow-one",
  run_id: "report-one",
  available: true,
  status: "succeeded",
};
it("identifies the exact saved report used for the reply", () => {
  render(
    <MemoryRouter>
      <AgentResultSources sources={[source]} />
    </MemoryRouter>,
  );
  expect(screen.getByText(/Using a stored agent report/)).toBeTruthy();
  expect(screen.getByRole("link").getAttribute("href")).toBe(
    "/runs/report-one",
  );
});
it("labels a bounded excerpt and preserves transcript keyboard selection", () => {
  render(
    <MemoryRouter>
      <AgentResultSources
        sources={[
          {
            ...source,
            truncated: true,
            included_characters: 1200,
            total_characters: 2400,
          },
        ]}
        tabIndex={-1}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(/excerpt 1200 \/ 2400/)).toBeTruthy();
  expect(screen.getByRole("link").tabIndex).toBe(-1);
});
it("does not claim an unavailable report was read", () => {
  render(
    <MemoryRouter>
      <AgentResultSources sources={[{ ...source, available: false }]} />
    </MemoryRouter>,
  );
  expect(screen.getByText(/Agent report unavailable/)).toBeTruthy();
  expect(screen.queryByText(/Using a stored agent report/)).toBeNull();
});
it("shows unfinished status and uses its original workflow link", () => {
  render(
    <MemoryRouter>
      <AgentResultSources
        sources={[
          {
            ...source,
            run_id: undefined,
            available: false,
            status: "waiting_for_approval",
          },
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(/waiting for approval/)).toBeTruthy();
  expect(screen.getByRole("link").getAttribute("href")).toBe(
    "/runs/workflow-one",
  );
});
