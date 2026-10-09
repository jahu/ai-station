import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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

function overview() {
  const agent = {
    id: "agent",
    name: "Morning review",
    model: "local",
    trigger: "interval",
    next_run_at: "2026-09-25T10:00:00Z",
    last_status: "failed",
    overdue: true,
  };
  return {
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
    interrupted_runs: [
      {
        id: "interrupted-run",
        title: "Image task needs inspection",
        executor_type: "photo_pipe",
        status: "interrupted",
        replay: false,
      },
    ],
  };
}

it("unifies attention with inspect and stop actions", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.includes("/acknowledge") && options?.method === "POST") {
      return { ok: true, json: async () => ({ id: "interrupted-run" }) };
    }
    if (path === "/api/runs/run/cancel" && options?.method === "POST") {
      return {
        ok: true,
        json: async () => ({ id: "run", status: "canceled" }),
      };
    }
    return { ok: true, json: async () => overview() };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("heading", { name: "Needs attention · 3" });
  expect(
    screen.getByRole("link", { name: /My conversation/ }).getAttribute("href"),
  ).toBe("/chat/chat");
  expect(
    screen.getByRole("link", { name: /Report.md/ }).getAttribute("href"),
  ).toBe("/library/artifact");
  expect(
    screen
      .getByRole("link", { name: /photo_pipe · host running/ })
      .getAttribute("href"),
  ).toBe("/runs/run");
  expect(
    screen
      .getByRole("link", { name: /Agent workflow failed/ })
      .getAttribute("href"),
  ).toBe("/runs/failed-run");
  expect(
    screen
      .getByRole("link", { name: /Image task needs inspection/ })
      .getAttribute("href"),
  ).toBe("/runs/interrupted-run");
  expect(screen.getByText(/Due \/ waiting for scheduler/)).toBeTruthy();
  expect(screen.getByText(/external · Process/)).toBeTruthy();
  expect(screen.getByText(/Stale/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Mark inspected" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] ===
            "/api/maintenance/interrupted/interrupted-run/acknowledge" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/runs/run/cancel" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
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
  expect(screen.queryByText("Nothing needs you right now")).toBeNull();
});
