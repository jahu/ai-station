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
          : url.endsWith("/llama")
            ? { models: [], instances: [] }
            : url.includes("/skills")
              ? []
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
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills")
            ? []
            : url.endsWith("tools")
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
                  search_query: "",
                  fetch_urls: [],
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
it("saves a reviewed public query separately from the private goal without activation", async () => {
  let agent = {
    id: "draft",
    name: "Research",
    description: "",
    goal: "Private project context",
    system_prompt: "",
    model: "local",
    search_query: "",
    tools: ["web_search"],
    trigger: "interval",
    interval_seconds: 3600,
    cron_expr: "",
    run_at: null,
    maximum_runtime: 600,
    output_expectation: "Report",
    project_id: null,
    enabled: false,
    updated_at: "2026-09-30T12:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: ["network_read"],
    runs: [],
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options) agent = { ...agent, ...JSON.parse(options.body as string) };
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills")
              ? []
              : url.endsWith("/tools")
                ? [
                    {
                      name: "web_search",
                      description: "Search public sources",
                      operational: true,
                      required_permissions: ["network_read"],
                    },
                  ]
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  const query = await screen.findByLabelText("Public search query");
  expect((query as HTMLInputElement).required).toBe(true);
  fireEvent.change(query, { target: { value: "open weight language models" } });
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  const write = fetch.mock.calls.find((c) => c[1])!;
  expect(JSON.parse(write[1]!.body as string)).toMatchObject({
    search_query: "open weight language models",
    goal: "Private project context",
    enabled: false,
    tools: ["web_search"],
  });
});
it("saves reviewed public fetch URLs separately from the private goal", async () => {
  let agent = {
    id: "draft",
    name: "Pages",
    description: "",
    goal: "Private project context",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    tools: ["http_fetch"],
    trigger: "manual",
    interval_seconds: null,
    cron_expr: "",
    run_at: null,
    maximum_runtime: 600,
    output_expectation: "Report",
    project_id: null,
    enabled: false,
    updated_at: "2026-10-09T12:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: ["network_read"],
    runs: [],
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options) agent = { ...agent, ...JSON.parse(options.body as string) };
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills")
              ? []
              : url.endsWith("/tools")
                ? [
                    {
                      name: "http_fetch",
                      description: "Fetch a public HTTP URL",
                      operational: true,
                      required_permissions: ["network_read"],
                    },
                  ]
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  const urls = await screen.findByLabelText("Public URLs to fetch");
  expect((urls as HTMLTextAreaElement).required).toBe(true);
  fireEvent.change(urls, {
    target: { value: "https://www.example.com/\nhttps://docs.example.org/a" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    fetch_urls: ["https://www.example.com/", "https://docs.example.org/a"],
    goal: "Private project context",
    enabled: false,
    tools: ["http_fetch"],
  });
});
it("lets a reviewer attach an installed skill without showing extra tools", async () => {
  let agent = {
    id: "draft",
    name: "Brief",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    trigger: "manual",
    interval_seconds: null,
    cron_expr: "",
    run_at: null,
    maximum_runtime: 600,
    output_expectation: "Report",
    project_id: null,
    enabled: false,
    updated_at: "2026-10-09T12:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: [] as string[],
    runs: [],
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options) agent = { ...agent, ...JSON.parse(options.body as string) };
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills")
              ? [
                  {
                    id: "daily-brief",
                    name: "Daily brief",
                    version: "1.0.0",
                    description: "Local status format",
                    required_permissions: [],
                    instructions: "Always mention GPU memory.",
                  },
                ]
              : url.endsWith("/tools")
                ? []
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  const box = await screen.findByRole("checkbox");
  fireEvent.click(box);
  expect(await screen.findByText("Always mention GPU memory.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    skills: ["daily-brief"],
    enabled: false,
    tools: [],
  });
});
