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
import type { Run } from "../api";
import AgentCodeWorkspace from "./AgentCodeWorkspace";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
const proposal = {
  id: "proposal",
  task_id: "agent-task",
  agent_id: "builder",
  executor_type: "local_proposal",
  capability: "coding.local",
  status: "succeeded",
  created_at: "2026-10-22T00:00:00Z",
  parameters: { prompt: "Create a sales report" },
  summary: "Report script created",
  metadata: { execution_location: "local" },
} as Run;
function mount(runs: Run[]) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/agents/builder?view=workspace"]}>
        <AgentCodeWorkspace runs={runs} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function backend(run: Run = proposal) {
  let runs = [run];
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST" && path.endsWith("/messages")) {
      const next = { ...run, id: "continuation", status: "queued" };
      runs = [...runs, next];
      return { ok: true, json: async () => next };
    }
    if (options?.method === "POST" && path.endsWith("/cancel"))
      return { ok: true, json: async () => ({ canceled: true }) };
    return {
      ok: true,
      json: async () => ({
        id: "agent-task",
        title: "Sales report",
        project_name: "Private agent workspace",
        project_id: "project",
        status: runs.at(-1)?.status,
        runs,
      }),
    };
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
it("does not load an older task while the current agent workspace is preparing", () => {
  const fetch = backend();
  mount([
    {
      ...proposal,
      task_id: "new-task",
      executor_type: "agent_workflow",
      metadata: {},
    },
    proposal,
  ]);
  expect(screen.getByText(/Preparing the workspace/)).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Open task history" })).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
it("continues the existing local task from the agent workspace with its expected proposal and Stop", async () => {
  const fetch = backend();
  mount([proposal]);
  await screen.findByText("Report script created");
  expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "Open task history" })
      .getAttribute("href"),
  ).toBe("/coding/agent-task");
  fireEvent.change(
    screen.getByRole("textbox", { name: "Follow-up instruction" }),
    { target: { value: "Add monthly totals" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/coding/sessions/agent-task/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          prompt: "Add monthly totals",
          expected_run_id: "proposal",
          external_ai: false,
        }),
      }),
    ),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/coding/sessions/agent-task/cancel",
      { method: "POST" },
    ),
  );
  expect(
    fetch.mock.calls.filter(([, options]) => options).map(([path]) => path),
  ).toEqual([
    "/api/coding/sessions/agent-task/messages",
    "/api/coding/sessions/agent-task/cancel",
  ]);
});
it("keeps the per-turn external consent guard in the embedded view", async () => {
  const fetch = backend({
    ...proposal,
    executor_type: "cursor_proposal",
    metadata: { execution_location: "external" },
  });
  mount([proposal]);
  await screen.findByText("Report script created");
  fireEvent.change(
    screen.getByRole("textbox", { name: "Follow-up instruction" }),
    { target: { value: "Add a chart" } },
  );
  expect(
    (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    screen.getByRole("checkbox", { name: /Share this turn/ }),
  ).toBeTruthy();
  expect(fetch.mock.calls.every(([, options]) => !options)).toBe(true);
});
