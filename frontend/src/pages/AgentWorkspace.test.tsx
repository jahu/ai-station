import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { AgentDetail } from "./Agents";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function setup({ draft = false, view = "" } = {}) {
  let agent = {
    id: "analyst",
    name: "Sales analyst",
    description: "",
    goal: "Analyze sales",
    system_prompt: "",
    model: "local",
    tools: [],
    skills: [],
    search_query: "",
    fetch_urls: [],
    trigger: "manual",
    cron_expr: "",
    interval_seconds: null,
    run_at: null,
    maximum_runtime: 600,
    output_expectation: "Report",
    require_approval: false,
    workflow_mode: "sequential",
    tool_calling: "none",
    retry_policy: { mode: "none" },
    notification_policy: {},
    project_id: null,
    enabled: !draft,
    updated_at: "2026-10-22T00:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: [],
    runs: [] as Record<string, unknown>[],
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/agents/analyst/run") && options?.method === "POST") {
      agent = {
        ...agent,
        runs: [
          {
            id: "queued-run",
            task_id: "task",
            executor_type: "agent_workflow",
            capability: "agent.workflow",
            status: "queued",
            created_at: "2026-10-22T00:00:00Z",
            parameters: {},
          },
        ],
      };
      return { ok: true, json: async () => ({ id: "queued-run" }) };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/agents/analyst")
          ? agent
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.endsWith("/llama")
              ? { models: [], instances: [] }
              : [],
    };
  });
  vi.stubGlobal("fetch", fetch);
  function Location() {
    const location = useLocation();
    const navigate = useNavigate();
    return (
      <>
        <output aria-label="Current location">
          {location.pathname + location.search}
        </output>
        <button onClick={() => navigate(-1)}>Go back</button>
      </>
    );
  }
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/agents/analyst" + view]}>
        <Location />
        <Routes>
          <Route path="/agents/:id" element={<AgentDetail />} />
          <Route path="/runs/:id" element={<h1>Run inspector</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

it("opens an enabled agent in its workspace and switches views without losing unsaved instructions", async () => {
  const fetch = setup();
  await screen.findByRole("heading", { name: "Execution history" });
  expect(screen.queryByRole("heading", { name: "Definition" })).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Settings" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Goal" }), {
    target: { value: "Keep this unsaved goal" },
  });
  fireEvent.click(screen.getByRole("link", { name: "Workspace" }));
  expect(screen.queryByRole("textbox", { name: "Goal" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Go back" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("textbox", {
          name: "Goal",
        }) as HTMLTextAreaElement
      ).value,
    ).toBe("Keep this unsaved goal"),
  );
  expect(
    screen.getByRole("link", { name: "Settings" }).getAttribute("aria-current"),
  ).toBe("page");
  expect(fetch.mock.calls.every(([, options]) => !options)).toBe(true);
});

it("opens a fresh inactive draft in settings without enabling it", async () => {
  const fetch = setup({ draft: true });
  await screen.findByRole("heading", { name: "Definition" });
  expect(
    (screen.getByRole("button", { name: "Run now" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(fetch.mock.calls.every(([, options]) => !options)).toBe(true);
});

it("respects an explicit workspace URL for an inactive draft", async () => {
  setup({ draft: true, view: "?view=workspace" });
  await screen.findByRole("heading", { name: "Execution history" });
  expect(
    screen
      .getByRole("link", { name: "Review agent settings" })
      .getAttribute("href"),
  ).toBe("/agents/analyst?view=settings");
  expect(screen.queryByRole("heading", { name: "Definition" })).toBeNull();
});

it("queues Run now once and stays on the agent workspace with Stop available", async () => {
  const fetch = setup({ view: "?view=settings" });
  await screen.findByRole("heading", { name: "Definition" });
  fireEvent.click(screen.getByRole("button", { name: "Run now" }));
  await screen.findByRole("button", { name: "Stop agent.workflow queued-r" });
  expect(
    screen.getByRole("status", { name: "Current location" }).textContent,
  ).toBe("/agents/analyst?view=workspace");
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect(fetch.mock.calls.filter(([, options]) => options)).toEqual([
    [
      "/api/agents/analyst/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ expected_updated_at: "2026-10-22T00:00:00Z" }),
      }),
    ],
  ]);
});
