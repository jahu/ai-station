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
        retry: { allowed: false, run_id: null },
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
    screen
      .getByRole("link", { name: "Inspect My conversation chat" })
      .getAttribute("href"),
  ).toBe("/chat/chat");
  expect(
    screen
      .getByRole("link", { name: "Inspect Report.md artifact" })
      .getAttribute("href"),
  ).toBe("/library/artifact");
  expect(
    screen
      .getByRole("link", { name: "Inspect Image task run" })
      .getAttribute("href"),
  ).toBe("/runs/run");
  expect(
    screen
      .getByRole("link", { name: "Inspect Agent workflow failed failed-r" })
      .getAttribute("href"),
  ).toBe("/runs/failed-run");
  expect(
    screen
      .getByRole("link", {
        name: "Inspect Image task needs inspection interrup",
      })
      .getAttribute("href"),
  ).toBe("/runs/interrupted-run");
  expect(screen.getByText(/Due \/ waiting for scheduler/)).toBeTruthy();
  expect(screen.getByText(/external · Process/)).toBeTruthy();
  expect(screen.getByText(/Stale/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Mark inspected Image task needs inspection interrup",
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
  fireEvent.click(screen.getByRole("button", { name: "Stop Image task run" }));
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
    screen.getByRole("button", {
      name: "Mark read Agent workflow failed notice",
    }),
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
    name: "Inspect Image task needs inspection interrup",
  });
  const notice = screen.getByRole("link", {
    name: "Inspect Agent workflow failed failed-r",
  });
  const active = screen.getByRole("link", { name: "Inspect Image task run" });
  expect(first.tabIndex).toBe(0);
  expect(notice.tabIndex).toBe(-1);
  expect(active.tabIndex).toBe(-1);
  expect(
    screen.getByRole("button", {
      name: "Retry as a new run Image task needs inspection interrup",
    }).tabIndex,
  ).toBe(0);
  expect(
    screen.getByRole("button", {
      name: "Mark inspected Image task needs inspection interrup",
    }).tabIndex,
  ).toBe(0);
  expect(
    screen.getByRole("button", { name: "Stop Image task run" }).tabIndex,
  ).toBe(-1);
  expect(
    screen.getByRole("button", {
      name: "Mark read Agent workflow failed notice",
    }).tabIndex,
  ).toBe(-1);
  fireEvent.keyDown(first.closest("ul") as HTMLElement, { key: "ArrowDown" });
  expect(notice.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(notice);
  expect(
    screen.getByRole("button", {
      name: "Mark read Agent workflow failed notice",
    }).tabIndex,
  ).toBe(0);
  fireEvent.keyDown(notice.closest("ul") as HTMLElement, { key: "End" });
  expect(active.tabIndex).toBe(0);
  expect(
    screen.getByRole("button", { name: "Stop Image task run" }).tabIndex,
  ).toBe(0);
  fireEvent.keyDown(active.closest("ul") as HTMLElement, { key: "Home" });
  expect(first.tabIndex).toBe(0);
});

it("retries an interrupted image from Home without opening the inspector", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (
      path === "/api/images/runs/interrupted-run/retry" &&
      options?.method === "POST"
    ) {
      return { ok: true, json: async () => ({ id: "retry-id", status: "queued" }) };
    }
    return { ok: true, json: async () => overview() };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Retry as a new run Image task needs inspection interrup",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/images/runs/interrupted-run/retry",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Needs attention · 3" }),
  ).toBeTruthy();
});

it("does not retry an interrupted non-image Run from Home", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        ...overview(),
        interrupted_runs: [
          {
            id: "coding-run",
            title: "Local proposal needs inspection",
            executor_type: "local_proposal",
            status: "interrupted",
            replay: false,
          },
        ],
        notices: [],
        active_runs: [],
      }),
    })),
  );
  mount();
  await screen.findByRole("button", {
    name: "Mark inspected Local proposal needs inspection coding-r",
  });
  expect(
    screen.queryByRole("button", { name: /Retry as a new run/ }),
  ).toBeNull();
});

it("retries a failed agent workflow from Home without Run now or the inspector", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (
      path === "/api/runs/parent-workflow/retry-workflow" &&
      options?.method === "POST"
    ) {
      return {
        ok: true,
        json: async () => ({ id: "retry-run", status: "queued" }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        ...overview(),
        interrupted_runs: [],
        active_runs: [],
        notices: [
          {
            id: "notice",
            agent_id: "agent",
            run_id: "failed-run",
            kind: "failed",
            title: "Agent workflow failed",
            created_at: "2026-09-25T10:00:00Z",
            retry: { allowed: true, run_id: "parent-workflow" },
          },
        ],
      }),
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Retry as a new workflow Agent workflow failed notice",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/parent-workflow/retry-workflow",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    fetch.mock.calls.some((call) =>
      String(call[0]).includes("/agents/agent/run"),
    ),
  ).toBe(false);
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Needs attention · 1" }),
  ).toBeTruthy();
});

it("grants a parked Run from Home without starting inference", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/runs/parked/approval" && options?.method === "POST") {
      expect(JSON.parse(String(options.body))).toEqual({
        resolution: "granted",
      });
      return {
        ok: true,
        json: async () => ({ id: "parked", status: "queued" }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        ...overview(),
        active_runs: [
          {
            id: "parked",
            title: "Morning review",
            executor_type: "agent",
            execution_target: "container",
            status: "waiting_for_approval",
          },
        ],
        notices: [],
        interrupted_runs: [],
      }),
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("heading", { name: "Needs attention · 1" });
  expect(screen.queryByRole("button", { name: /Stop/ })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Approve and queue Morning review parked",
    }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/runs/parked/approval" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("denies a parked Run from Home without restore or replay", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/runs/parked/approval" && options?.method === "POST") {
      expect(JSON.parse(String(options.body))).toEqual({
        resolution: "denied",
      });
      return {
        ok: true,
        json: async () => ({ id: "parked", status: "canceled" }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        ...overview(),
        active_runs: [
          {
            id: "parked",
            title: "Morning review",
            executor_type: "agent",
            execution_target: "container",
            status: "waiting_for_approval",
          },
        ],
        notices: [],
        interrupted_runs: [],
      }),
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("button", { name: "Deny Morning review parked" });
  fireEvent.click(
    screen.getByRole("button", { name: "Deny Morning review parked" }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/runs/parked/approval" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("moves through Home activity lists with unique inspect names", async () => {
  const data = overview();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        ...data,
        upcoming: [
          data.upcoming[0],
          {
            ...data.upcoming[0],
            id: "agent-two",
            name: "Evening digest",
            overdue: false,
          },
        ],
      }),
    })),
  );
  mount();
  const first = await screen.findByRole("link", {
    name: "Inspect scheduled Morning review agent",
  });
  const second = screen.getByRole("link", {
    name: "Inspect scheduled Evening digest agent-tw",
  });
  expect(first.getAttribute("href")).toBe("/agents/agent");
  expect(second.getAttribute("href")).toBe("/agents/agent-two");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  fireEvent.keyDown(first.closest("ul") as HTMLElement, { key: "ArrowDown" });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(
    screen.getByRole("link", { name: "Inspect Morning review agent" }).getAttribute(
      "href",
    ),
  ).toBe("/agents/agent");
  expect(
    screen
      .getByRole("link", { name: "Inspect observation Ollama runtime" })
      .getAttribute("href"),
  ).toBe("/system");
});

it("opens a linked project from Home without Enable or Run now", async () => {
  const data = overview();
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("/dashboard")
        ? {
            ...data,
            agents: [{ ...data.agents[0], project_id: "project-1" }],
          }
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  const inspect = await screen.findByRole("link", {
    name: "Inspect project project-1",
  });
  expect(inspect.getAttribute("href")).toBe("/projects/project-1");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs agent" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1&agent_id=agent");
  expect(screen.getByText(/Linked project/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(fetch).toHaveBeenCalledWith("/api/dashboard", undefined);
});

it("opens the tagged agent from in-progress and waiting Home Runs without Enable or Run now", async () => {
  const data = overview();
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("/dashboard")
        ? {
            ...data,
            interrupted_runs: [],
            notices: [],
            active_runs: [
              {
                id: "running-agent",
                title: "Morning review",
                executor_type: "agent_workflow",
                execution_target: "container",
                status: "running",
                agent_id: "agent",
                project_id: "project-1",
              },
              {
                id: "parked",
                title: "Evening check",
                executor_type: "agent_workflow",
                execution_target: "container",
                status: "waiting_for_approval",
                agent_id: "agent",
                project_id: "project-1",
              },
            ],
          }
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  const inspectAgent = await screen.findAllByRole("link", {
    name: "Inspect agent agent",
  });
  expect(inspectAgent).toHaveLength(2);
  expect(inspectAgent[0].getAttribute("href")).toBe("/agents/agent");
  expect(
    screen.getAllByRole("link", { name: "Inspect project project-1" })[0].getAttribute(
      "href",
    ),
  ).toBe("/projects/project-1");
  expect(
    screen
      .getAllByRole("link", { name: "View tagged Runs agent" })[0]
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1&agent_id=agent");
  expect(
    screen.getByRole("button", { name: "Stop Morning review running-" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", {
      name: "Approve and queue Evening check parked",
    }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("opens the tagged agent from a Home notice without Enable or Run now", async () => {
  const data = overview();
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("/dashboard")
        ? {
            ...data,
            interrupted_runs: [],
            active_runs: [],
            notices: [
              {
                ...data.notices[0],
                project_id: "project-1",
              },
            ],
          }
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    (
      await screen.findByRole("link", { name: "Inspect agent agent" })
    ).getAttribute("href"),
  ).toBe("/agents/agent");
  expect(
    screen.getByRole("link", { name: "Inspect project project-1" }).getAttribute(
      "href",
    ),
  ).toBe("/projects/project-1");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs agent" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1&agent_id=agent");
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
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
