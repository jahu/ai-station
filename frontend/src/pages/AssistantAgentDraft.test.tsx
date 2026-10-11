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
import { AssistantAgentDraft } from "./AssistantAgentDraft";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const draft = {
  id: "agent-one",
  name: "Morning briefing",
  model: "local-27b",
  enabled: false,
  updated_at: "2026-10-11T10:00:00Z",
  goal: "Summarize GPU telemetry every weekday.",
  tools: ["telemetry", "web_search"],
  skills: ["station-briefing"],
  trigger: "cron",
  cron_expr: "0 7 * * 1-5",
  require_approval: true,
  workflow_mode: "gated",
  search_query: "workstation GPU news",
  last_status: "",
  last_run_at: null as string | null,
  next_run_at: null as string | null,
  retry_policy: { mode: "none" as string },
  runs: [] as {
    id: string;
    capability: string;
    status: string;
    created_at: string;
    parameters?: { tool?: string };
    retry?: { allowed: boolean; retry_run_id?: string | null };
  }[],
};

function mount(agent = draft) {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      String(path).endsWith("/enabled")
        ? { ...agent, enabled: true, updated_at: "2026-10-11T10:01:00Z" }
        : String(path).endsWith("/duplicate")
          ? {
              ...agent,
              id: "agent-copy",
              name: `${agent.name} (copy)`,
              enabled: false,
              last_run_at: null,
              next_run_at: null,
              last_status: "",
              runs: [],
            }
          : String(path).includes("/retry-workflow")
            ? {
                id: "retry-run",
                capability: "agent.workflow",
                status: "queued",
                retry: { allowed: false, retry_of: "fail-run-dddd" },
              }
            : agent,
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantAgentDraft agentId={agent.id} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

it("inspects the saved definition without queueing Run now", async () => {
  const fetch = mount();
  expect(await screen.findByText("0 7 * * 1-5 (UTC)")).toBeTruthy();
  expect(screen.getByText("telemetry, web_search")).toBeTruthy();
  expect(
    screen.getByText("Summarize GPU telemetry every weekday."),
  ).toBeTruthy();
  expect(
    screen.getByText("No executions yet. Run now stays in Agents."),
  ).toBeTruthy();
  expect(
    screen.queryByRole("region", { name: "Execution history" }),
  ).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
});

it("enables a disabled draft from the conversation without inventing a Run", async () => {
  const fetch = mount();
  expect(await screen.findByText("Morning briefing")).toBeTruthy();
  expect(screen.getByText(/Disabled draft/)).toBeTruthy();
  expect(screen.getByText("0 7 * * 1-5 (UTC)")).toBeTruthy();
  expect(screen.getByText("telemetry, web_search")).toBeTruthy();
  expect(screen.getByText("station-briefing")).toBeTruthy();
  expect(screen.getByText("workstation GPU news")).toBeTruthy();
  expect(screen.getByText("Required before each Run")).toBeTruthy();
  expect(screen.getByText("Gated")).toBeTruthy();
  expect(
    screen.getByText("Summarize GPU telemetry every weekday."),
  ).toBeTruthy();
  expect(screen.getByText(/does not invent a conversation Run/)).toBeTruthy();
  expect(
    screen.getByText(/Run now, tools and schedule stay in Agents/),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Enable saved definition agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one/enabled",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
          enabled: true,
        }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(
    screen
      .getByRole("link", { name: "Review agent agent-on" })
      .getAttribute("href"),
  ).toBe("/agents/agent-one");
});

it("inspects ordinary execution history from the conversation without Run now", async () => {
  const fetch = mount({
    ...draft,
    enabled: true,
    last_status: "succeeded",
    last_run_at: "2026-10-11T11:00:00Z",
    next_run_at: "2026-10-12T07:00:00Z",
    runs: [
      {
        id: "run-one-aaaa",
        capability: "agent.workflow",
        status: "succeeded",
        created_at: "2026-10-11T11:00:00Z",
      },
      {
        id: "run-two-bbbb",
        capability: "agent.step",
        status: "succeeded",
        created_at: "2026-10-11T11:01:00Z",
        parameters: { tool: "memory_search" },
      },
    ],
  });
  expect(await screen.findByText(/Enabled/)).toBeTruthy();
  expect(screen.getByText(/· succeeded/)).toBeTruthy();
  const first = await screen.findByRole("link", {
    name: "Inspect agent.workflow run-one-",
  });
  const second = screen.getByRole("link", {
    name: "Inspect memory_search run-two-",
  });
  expect(first.getAttribute("href")).toBe("/runs/run-one-aaaa");
  expect(second.getAttribute("href")).toBe("/runs/run-two-bbbb");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Execution history" }),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
  expect(screen.queryByRole("button", { name: /Run now/ })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("links a waiting approval from conversation history without starting tools", async () => {
  mount({
    ...draft,
    enabled: true,
    runs: [
      {
        id: "wait-run-cccc",
        capability: "agent.workflow",
        status: "waiting_for_approval",
        created_at: "2026-10-11T12:00:00Z",
      },
    ],
  });
  expect(
    (
      await screen.findByRole("link", { name: "Review waiting Run wait-run" })
    ).getAttribute("href"),
  ).toBe("/runs/wait-run-cccc");
  expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
});

it("pauses an enabled agent from the conversation without starting a Run", async () => {
  const enabled = { ...draft, enabled: true };
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      String(path).endsWith("/enabled")
        ? { ...enabled, enabled: false }
        : enabled,
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantAgentDraft agentId={enabled.id} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Pause agent agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one/enabled",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
          enabled: false,
        }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("duplicates as a disabled draft from the conversation without Run now", async () => {
  const fetch = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Duplicate as draft agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one/duplicate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
        }),
      }),
    ),
  );
  expect(screen.getByText("Morning briefing (copy)")).toBeTruthy();
  expect(screen.getByText(/Copied as disabled draft/)).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Review copy agent-co" })
      .getAttribute("href"),
  ).toBe("/agents/agent-copy");
  expect(screen.queryByRole("button", { name: /Run now/ })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
});

it("retries a failed workflow from conversation history without Run now", async () => {
  const fetch = mount({
    ...draft,
    enabled: true,
    retry_policy: { mode: "manual" },
    last_status: "failed",
    last_run_at: "2026-10-11T12:00:00Z",
    runs: [
      {
        id: "fail-run-dddd",
        capability: "agent.workflow",
        status: "failed",
        created_at: "2026-10-11T12:00:00Z",
        retry: { allowed: true, retry_run_id: null },
      },
    ],
  });
  expect(
    await screen.findByText("Manual retry of a failed snapshot"),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Run now/ })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Retry as a new workflow fail-run",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/fail-run-dddd/retry-workflow",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    screen
      .getByRole("link", { name: "Inspect retry retry-ru" })
      .getAttribute("href"),
  ).toBe("/runs/retry-run");
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
