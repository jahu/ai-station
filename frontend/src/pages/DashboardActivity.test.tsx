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
    if (path === "/api/notices/notice/read" && options?.method === "POST") {
      expect(JSON.parse(String(options.body))).toEqual({ read: true });
      return {
        ok: true,
        json: async () => ({ id: "notice", read_at: "2026-09-25T10:01:00Z" }),
      };
    }
    return { ok: true, json: async () => overview() };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("heading", { name: "Needs attention · 3" });
  expect(
    screen.getByRole("region", { name: "Needs attention · 3" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "View all runs" }).getAttribute("href"),
  ).toBe("/runs");
  expect(
    screen.getByRole("link", { name: "View all conversations" }).getAttribute("href"),
  ).toBe("/chat");
  expect(
    screen.getByRole("link", { name: "Inspect My conversation" }).getAttribute("href"),
  ).toBe("/chat/chat");
  expect(
    screen.getByRole("link", { name: "Inspect Report.md" }).getAttribute("href"),
  ).toBe("/library/artifact");
  expect(
    screen
      .getByRole("link", { name: "Inspect Image task" })
      .getAttribute("href"),
  ).toBe("/runs/run");
  expect(
    screen
      .getByRole("link", { name: "Inspect Agent workflow failed" })
      .getAttribute("href"),
  ).toBe("/runs/failed-run");
  expect(
    screen
      .getByRole("link", { name: "Inspect Image task needs inspection" })
      .getAttribute("href"),
  ).toBe("/runs/interrupted-run");
  expect(screen.getByText(/Due \/ waiting for scheduler/)).toBeTruthy();
  expect(screen.getByText(/external · Process/)).toBeTruthy();
  expect(screen.getByText(/Stale/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Mark inspected Image task needs inspection",
    }),
  );
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
  fireEvent.click(screen.getByRole("button", { name: "Stop Image task" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/runs/run/cancel" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Mark read Agent workflow failed" }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/notices/notice/read" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
});
it("moves through the attention list with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => overview() })),
  );
  mount();
  const first = await screen.findByRole("link", {
    name: "Inspect Image task needs inspection",
  });
  const notice = screen.getByRole("link", {
    name: "Inspect Agent workflow failed",
  });
  const active = screen.getByRole("link", { name: "Inspect Image task" });
  expect(first.tabIndex).toBe(0);
  expect(notice.tabIndex).toBe(-1);
  expect(active.tabIndex).toBe(-1);
  expect(
    screen.getByRole("button", {
      name: "Mark inspected Image task needs inspection",
    }).tabIndex,
  ).toBe(0);
  expect(screen.getByRole("button", { name: "Stop Image task" }).tabIndex).toBe(
    -1,
  );
  expect(
    screen.getByRole("button", { name: "Mark read Agent workflow failed" })
      .tabIndex,
  ).toBe(-1);
  fireEvent.keyDown(first.closest("ul") as HTMLElement, { key: "ArrowDown" });
  expect(notice.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(notice);
  expect(
    screen.getByRole("button", { name: "Mark read Agent workflow failed" })
      .tabIndex,
  ).toBe(0);
  fireEvent.keyDown(notice.closest("ul") as HTMLElement, { key: "End" });
  expect(active.tabIndex).toBe(0);
  expect(screen.getByRole("button", { name: "Stop Image task" }).tabIndex).toBe(
    0,
  );
  fireEvent.keyDown(active.closest("ul") as HTMLElement, { key: "Home" });
  expect(first.tabIndex).toBe(0);
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
