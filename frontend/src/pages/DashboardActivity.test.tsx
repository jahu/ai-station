import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import DashboardActivity from "./DashboardActivity";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <DashboardActivity />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("links real activity and marks saved runtime and overdue schedule state", async () => {
  const agent = {
    id: "agent",
    name: "Morning review",
    model: "local",
    trigger: "interval",
    next_run_at: "2026-09-25T10:00:00Z",
    last_status: "failed",
    overdue: true,
  };
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      active_run_count: 12,
      enabled_agent_count: 1,
      active_runs: [
        {
          id: "run",
          title: "Image task",
          executor_type: "photo_pipe",
          execution_target: "host",
          status: "running",
        },
      ],
      upcoming: [agent],
      agents: [agent],
      conversations: [
        {
          id: "chat",
          title: "My conversation",
          model: "local",
          updated_at: "2026-09-25T10:00:00Z",
        },
      ],
      artifacts: [
        {
          id: "artifact",
          name: "Report.md",
          type: "markdown",
          created_at: "2026-09-25T10:00:00Z",
          has_thumbnail: false,
        },
      ],
      runtimes: [
        {
          id: "runtime",
          name: "Ollama",
          ownership: "external",
          source: "host_process",
          status: "observed",
          updated_at: "2026-09-25T10:00:00Z",
          stale: true,
        },
      ],
      unread_notice_count: 1,
      notices: [
        {
          id: "notice",
          agent_id: "agent",
          run_id: "failed-run",
          kind: "failed",
          title: "Agent workflow failed",
          created_at: "2026-09-25T10:00:00Z",
        },
      ],
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("heading", { name: "In progress · 12" });
  expect(
    screen.getByRole("link", { name: /My conversation/ }).getAttribute("href"),
  ).toBe("/chat/chat");
  expect(
    screen.getByRole("link", { name: /Report.md/ }).getAttribute("href"),
  ).toBe("/library/artifact");
  expect(
    screen.getByRole("link", { name: /Image task/ }).getAttribute("href"),
  ).toBe("/runs/run");
  expect(
    screen
      .getByRole("link", { name: /Agent workflow failed/ })
      .getAttribute("href"),
  ).toBe("/runs/failed-run");
  expect(screen.getByText(/Due \/ waiting for scheduler/)).toBeTruthy();
  expect(screen.getByText(/external · Process.*Stale/)).toBeTruthy();
  expect(fetch.mock.calls).toEqual([["/api/dashboard", undefined]]);
});
it("shows an error instead of claiming there is no activity", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: false,
      json: async () => ({ detail: "Database unavailable" }),
    })),
  );
  mount();
  await screen.findByText("Database unavailable");
  expect(screen.queryByText("No active runs")).toBeNull();
});
