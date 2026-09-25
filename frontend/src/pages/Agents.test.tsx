import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Agents, AgentDetail } from "./Agents";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(detail = false) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[detail ? "/agents/draft" : "/agents"]}>
        <Routes>
          <Route path="/agents" element={<Agents />} />
          <Route
            path="/agents/:id"
            element={detail ? <AgentDetail /> : <h1>Review draft</h1>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("creates a reviewable draft without enabling or running it", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options
        ? { id: "draft" }
        : url.includes("provider")
          ? { models: ["local"], default_model: "local" }
          : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("heading", { name: "No agents in this view" });
  fireEvent.change(screen.getByLabelText("Instruction"), {
    target: { value: "Every morning summarize memory" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
  await screen.findByRole("heading", { name: "Review draft" });
  const writes = fetch.mock.calls.filter((call) => call[1]);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/agents/draft");
  expect(JSON.parse(writes[0][1]!.body as string)).toEqual({
    instruction: "Every morning summarize memory",
    model: "local",
  });
});
it("keeps a draft inactive and makes unsupported tools inspectable and removable", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () =>
      url.endsWith("tools")
        ? [
            {
              name: "web_search",
              description: "Unavailable search",
              operational: false,
              required_permissions: [],
            },
          ]
        : {
            id: "draft",
            name: "Draft",
            description: "",
            goal: "Research",
            system_prompt: "",
            model: "local",
            tools: ["web_search"],
            trigger: "manual",
            cron_expr: "",
            interval_seconds: null,
            run_at: null,
            maximum_runtime: 600,
            output_expectation: "Report",
            project_id: null,
            enabled: false,
            updated_at: "2026-09-25T12:00:00Z",
            next_run_at: null,
            last_run_at: null,
            last_status: "",
            failure_count: 0,
            effective_permissions: [],
            runs: [],
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  await screen.findByRole("heading", { name: "Definition" });
  expect(
    (screen.getByRole("button", { name: "Run now" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  const checkbox = await screen.findByRole("checkbox");
  expect((checkbox as HTMLInputElement).checked).toBe(true);
  fireEvent.click(checkbox);
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect((checkbox as HTMLInputElement).disabled).toBe(true);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
