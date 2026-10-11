import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("heading", { name: "No agents in this view" });
  expect(screen.getByText(/disabled definition/i)).toBeTruthy();
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
          : url.includes("/skills") || url.includes("/projects")
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
                  search_query: "workstation news",
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
  const checkbox = await screen.findByRole("checkbox", { name: /web_search/i });
  expect((checkbox as HTMLInputElement).checked).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByText("Unavailable tools prevent activation: web_search."),
  ).toBeTruthy();
  fireEvent.click(checkbox);
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect((checkbox as HTMLInputElement).disabled).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
it("enables a draft after unavailable tools are removed and saved", async () => {
  let agent = {
    id: "draft",
    name: "Draft",
    description: "",
    goal: "Research",
    system_prompt: "",
    model: "local",
    tools: ["web_search"],
    search_query: "workstation news",
    fetch_urls: [] as string[],
    trigger: "manual",
    cron_expr: "",
    interval_seconds: null as number | null,
    run_at: null as string | null,
    maximum_runtime: 600,
    output_expectation: "Report",
    project_id: null as string | null,
    enabled: false,
    updated_at: "2026-09-25T12:00:00Z",
    next_run_at: null as string | null,
    last_run_at: null as string | null,
    last_status: "",
    failure_count: 0,
    effective_permissions: [] as string[],
    runs: [] as unknown[],
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (
      options &&
      String(url).includes("/agents/draft") &&
      !String(url).endsWith("/enabled")
    ) {
      agent = {
        ...agent,
        ...JSON.parse(String(options.body)),
        updated_at: "2026-09-25T12:01:00Z",
      };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : url.endsWith("/tools")
                ? [
                    {
                      name: "web_search",
                      description: "Unavailable search",
                      operational: false,
                      required_permissions: [],
                    },
                  ]
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  await screen.findByRole("heading", { name: "Definition" });
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(await screen.findByRole("checkbox", { name: /web_search/i }));
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
});
it("keeps Enable disabled when a saved skill is missing from the catalog", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects")
            ? []
            : url.endsWith("/tools")
              ? []
              : {
                  id: "draft",
                  name: "Draft",
                  description: "",
                  goal: "Research",
                  system_prompt: "",
                  model: "local",
                  tools: [] as string[],
                  skills: ["gone-skill"],
                  search_query: "",
                  fetch_urls: [] as string[],
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
                  effective_permissions: [] as string[],
                  runs: [] as unknown[],
                },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  expect(
    await screen.findByText("Missing skills prevent activation: gone-skill."),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
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
            : url.includes("/skills") || url.includes("/projects")
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
            : url.includes("/skills") || url.includes("/projects")
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
            : url.includes("/projects")
              ? []
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
  const box = await screen.findByRole("checkbox", { name: /Daily brief/i });
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
it("saves gated workflow steps without enabling the draft", async () => {
  let agent = {
    id: "draft",
    name: "Guarded",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    require_approval: false,
    workflow_mode: "sequential",
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
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : url.endsWith("/tools")
                ? []
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(await screen.findByRole("radio", { name: /Gated/i }));
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    workflow_mode: "gated",
    enabled: false,
  });
});
it("saves bounded tool calling without enabling the draft", async () => {
  let agent = {
    id: "draft",
    name: "Guarded",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    require_approval: false,
    workflow_mode: "sequential",
    tool_calling: "none",
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
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : url.endsWith("/tools")
                ? []
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: /Bounded tool calling during the report/i,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    tool_calling: "bounded",
    enabled: false,
  });
});
it("saves retry and notification policies without enabling the draft", async () => {
  let agent = {
    id: "draft",
    name: "Guarded",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    require_approval: false,
    workflow_mode: "sequential",
    retry_policy: { mode: "none" },
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
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
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : url.endsWith("/tools")
                ? []
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(await screen.findByRole("radio", { name: /Manual retry/i }));
  fireEvent.click(
    screen.getByRole("checkbox", { name: /When a workflow or report fails/i }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    retry_policy: { mode: "manual" },
    notification_policy: { on_failure: true },
    enabled: false,
  });
});
it("saves an explicit approval requirement without enabling the draft", async () => {
  let agent = {
    id: "draft",
    name: "Guarded",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    require_approval: false,
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
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : url.endsWith("/tools")
                ? []
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  const box = await screen.findByRole("checkbox", {
    name: /Require approval before each Run/i,
  });
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    require_approval: true,
    enabled: false,
  });
});
it("saves a linked project from the definition without enabling or running", async () => {
  let agent = {
    id: "draft",
    name: "Guarded",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    require_approval: false,
    trigger: "manual",
    interval_seconds: null,
    cron_expr: "",
    run_at: null,
    maximum_runtime: 600,
    output_expectation: "Report",
    project_id: null as string | null,
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
            : url.includes("/projects")
              ? [{ id: "project-1", name: "Workstation docs" }]
              : url.includes("/skills")
                ? []
                : url.endsWith("/tools")
                  ? []
                  : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  const none = (await screen.findByRole("radio", {
    name: "Linked project none draft",
  })) as HTMLInputElement;
  expect(none.checked).toBe(true);
  expect(
    screen.getByText(/does not grant coding, Git or repository access/),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("radio", { name: "Linked project project-1" }),
  );
  expect(
    fetch.mock.calls.every((call) => call[1]?.method !== "PUT"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1]?.method === "PUT")).toHaveLength(
      1,
    ),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1]?.method === "PUT")![1]!.body as string),
  ).toMatchObject({
    project_id: "project-1",
    enabled: false,
    expected_updated_at: "2026-10-09T12:00:00Z",
  });
  expect(
    (
      screen.getByRole("radio", {
        name: "Linked project project-1",
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  const project = await screen.findByRole("link", {
    name: "Inspect project project-1",
  });
  expect(project.getAttribute("href")).toBe("/projects/project-1");
  expect(project.textContent).toBe("Workstation docs");
  const tagged = screen.getByRole("link", {
    name: "View tagged Runs draft",
  });
  expect(tagged.getAttribute("href")).toBe(
    "/runs?project_id=project-1&agent_id=draft",
  );
});
it("lists other agents on the same linked project without Enable or Run now", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/projects")
            ? [{ id: "project-1", name: "Workstation docs" }]
            : url.includes("/skills") || url.endsWith("/tools")
              ? []
              : url.includes("project_id=project-1")
                ? [
                    {
                      id: "draft",
                      name: "Morning review",
                      goal: "Summarize",
                      model: "local",
                      enabled: false,
                      last_status: "",
                      next_run_at: null,
                    },
                    {
                      id: "agenttwo",
                      name: "Evening check",
                      goal: "Check GPUs",
                      model: "local",
                      enabled: true,
                      last_status: "succeeded",
                      next_run_at: null,
                    },
                  ]
                : {
                    id: "draft",
                    name: "Morning review",
                    description: "",
                    goal: "Summarize",
                    system_prompt: "",
                    model: "local",
                    tools: [],
                    search_query: "",
                    fetch_urls: [],
                    skills: [],
                    trigger: "manual",
                    cron_expr: "",
                    interval_seconds: null,
                    run_at: null,
                    maximum_runtime: 600,
                    output_expectation: "Report",
                    workflow_mode: "sequential",
                    tool_calling: "none",
                    retry_policy: { mode: "none" },
                    notification_policy: {
                      on_success: false,
                      on_failure: false,
                      on_approval: false,
                    },
                    project_id: "project-1",
                    enabled: false,
                    updated_at: "2026-10-09T12:00:00Z",
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
  expect(
    await screen.findByRole("heading", {
      name: "Other agents on this project",
    }),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", {
      name: "Inspect agent Evening check agenttwo",
    }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("link", {
      name: "Inspect agent Morning review draft",
    }),
  ).toBeNull();
  expect(
    fetch.mock.calls.some(
      (call) =>
        String(call[0]) ===
        "/api/agents?limit=50&offset=0&project_id=project-1",
    ),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("moves through linked projects with arrow keys without inventing a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/projects")
            ? [
                { id: "project-1", name: "Workstation docs" },
                { id: "project-2", name: "Second repo" },
              ]
            : url.includes("/skills") || url.endsWith("tools")
              ? []
              : {
                  id: "draft",
                  name: "Morning review",
                  description: "",
                  goal: "Summarize",
                  system_prompt: "",
                  model: "local",
                  tools: [],
                  search_query: "",
                  fetch_urls: [],
                  skills: [],
                  trigger: "manual",
                  cron_expr: "",
                  interval_seconds: null,
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
                  effective_permissions: [],
                  runs: [],
                },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  const none = (await screen.findByRole("radio", {
    name: "Linked project none draft",
  })) as HTMLInputElement;
  const first = screen.getByRole("radio", {
    name: "Linked project project-1",
  }) as HTMLInputElement;
  const second = screen.getByRole("radio", {
    name: "Linked project project-2",
  }) as HTMLInputElement;
  expect(none.checked).toBe(true);
  expect(none.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable project-link Run/),
  ).toBeTruthy();
  fireEvent.keyDown(none.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(first.tabIndex).toBe(0);
  expect(none.tabIndex).toBe(-1);
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Linked project project-1",
  );
  fireEvent.keyDown(first.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(first.checked).toBe(true);
  fireEvent.keyDown(first.closest(".agent-choice-list") as HTMLElement, {
    key: "End",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Linked project project-2",
  );
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
it("saves workflow memory without enabling the draft", async () => {
  let agent = {
    id: "draft",
    name: "Guarded",
    description: "",
    goal: "Summarize the workstation",
    system_prompt: "",
    model: "local",
    search_query: "",
    fetch_urls: [] as string[],
    skills: [] as string[],
    tools: [] as string[],
    require_approval: false,
    workflow_mode: "sequential",
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
            : url.includes("/skills") || url.includes("/projects")
              ? []
              : url.endsWith("/tools")
                ? [
                    {
                      name: "remember_workflow",
                      description: "Save workflow observations",
                      operational: true,
                      required_permissions: ["memory_write"],
                    },
                  ]
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: /Remember workflow observations/i,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await vi.waitFor(() =>
    expect(fetch.mock.calls.filter((c) => c[1])).toHaveLength(1),
  );
  expect(
    JSON.parse(fetch.mock.calls.find((c) => c[1])![1]!.body as string),
  ).toMatchObject({
    tools: ["remember_workflow"],
    enabled: false,
  });
  expect(
    screen.getByText(/Successful telemetry, public search and HTTP fetch/i),
  ).toBeTruthy();
});
it("shows a linked project name on the agent list without inventing a Run", async () => {
  const row = {
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: [],
    search_query: "",
    fetch_urls: [],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: "project-1",
    enabled: false,
    updated_at: "2026-10-09T12:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.includes("provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/projects")
              ? [{ id: "project-1", name: "Workstation docs" }]
              : url.includes("/agents")
                ? [{ ...row, id: "agentone", name: "Morning review" }]
                : [],
    })),
  );
  mount();
  expect(
    await screen.findByRole("link", {
      name: "Inspect Morning review agentone",
    }),
  ).toBeTruthy();
  expect(screen.getByText(/Linked project: Workstation docs/)).toBeTruthy();
  expect(
    screen.queryByRole("link", { name: "Inspect project project-1" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: /Enable|Run now/ }),
  ).toBeNull();
});
it("filters the agent list by linked project without inventing a Run", async () => {
  const row = {
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: [],
    search_query: "",
    fetch_urls: [],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    enabled: false,
    updated_at: "2026-10-09T12:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: [],
  };
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.includes("provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/projects")
            ? [{ id: "project-1", name: "Workstation docs" }]
            : url.includes("project_id=project-1")
              ? [
                  {
                    ...row,
                    id: "agentone",
                    name: "Morning review",
                    project_id: "project-1",
                  },
                ]
              : url.includes("/agents")
                ? [
                    {
                      ...row,
                      id: "agentone",
                      name: "Morning review",
                      project_id: "project-1",
                    },
                    {
                      ...row,
                      id: "agenttwo",
                      name: "Evening check",
                      project_id: null,
                    },
                  ]
                : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    await screen.findByRole("link", {
      name: "Inspect Evening check agenttwo",
    }),
  ).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Filter linked project" }), {
    target: { value: "project-1" },
  });
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents?limit=50&offset=0&project_id=project-1",
      undefined,
    ),
  );
  expect(
    await screen.findByRole("link", {
      name: "Inspect Morning review agentone",
    }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("link", { name: "Inspect Evening check agenttwo" }),
  ).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("moves through the agent list with arrow keys", async () => {
  const row = {
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: [],
    search_query: "",
    fetch_urls: [],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: null,
    enabled: false,
    updated_at: "2026-10-09T12:00:00Z",
    next_run_at: null,
    last_run_at: null,
    last_status: "",
    failure_count: 0,
    effective_permissions: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.includes("provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/agents")
              ? [
                  { ...row, id: "agentone", name: "Morning review" },
                  { ...row, id: "agenttwo", name: "Evening check" },
                ]
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : [],
    })),
  );
  mount();
  const first = await screen.findByRole("link", {
    name: "Inspect Morning review agentone",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Evening check agenttwo",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Agents" })).toBeTruthy();
  fireEvent.keyDown(first.closest(".memory-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".memory-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
it("moves through execution history with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
              ? []
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : {
                    id: "draft",
                    name: "Morning review",
                    description: "",
                    goal: "Summarize",
                    system_prompt: "",
                    model: "local",
                    tools: [],
                    search_query: "",
                    fetch_urls: [],
                    skills: [],
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
                    notification_policy: {
                      on_success: false,
                      on_failure: false,
                      on_approval: false,
                    },
                    project_id: null,
                    enabled: false,
                    updated_at: "2026-10-09T12:00:00Z",
                    next_run_at: null,
                    last_run_at: null,
                    last_status: "",
                    failure_count: 0,
                    effective_permissions: [],
                    runs: [
                      {
                        id: "run-one-aaaa",
                        capability: "agent.workflow",
                        status: "succeeded",
                        created_at: "2026-10-09T12:00:00Z",
                      },
                      {
                        id: "run-two-bbbb",
                        capability: "agent.step",
                        status: "succeeded",
                        created_at: "2026-10-09T12:01:00Z",
                        parameters: { tool: "memory_search" },
                      },
                    ],
                  },
    })),
  );
  mount(true);
  const first = await screen.findByRole("link", {
    name: "Inspect agent.workflow run-one-",
  });
  const second = screen.getByRole("link", {
    name: "Inspect memory_search run-two-",
  });
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
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", { name: "Inspect memory_search run-two-" })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
it("moves through skills and tools with arrow keys without inventing a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/projects")
            ? []
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
                {
                  id: "night-notes",
                  name: "Night notes",
                  version: "1.0.0",
                  description: "Evening recap",
                  required_permissions: [],
                  instructions: "Keep the recap short.",
                },
              ]
            : url.endsWith("tools")
              ? [
                  {
                    name: "memory_search",
                    description: "Search this agent’s memory",
                    operational: true,
                    required_permissions: [],
                  },
                  {
                    name: "http_fetch",
                    description: "GET reviewed public pages",
                    operational: true,
                    required_permissions: ["network_read"],
                  },
                ]
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : {
                    id: "draft",
                    name: "Morning review",
                    description: "",
                    goal: "Summarize",
                    system_prompt: "",
                    model: "local",
                    tools: [],
                    search_query: "",
                    fetch_urls: [],
                    skills: [],
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
                    notification_policy: {
                      on_success: false,
                      on_failure: false,
                      on_approval: false,
                    },
                    project_id: null,
                    enabled: false,
                    updated_at: "2026-10-09T12:00:00Z",
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
  const firstSkill = await screen.findByLabelText(
    "Skill Daily brief daily-brief",
  );
  const secondSkill = screen.getByLabelText("Skill Night notes night-notes");
  expect(firstSkill.tabIndex).toBe(0);
  expect(secondSkill.tabIndex).toBe(-1);
  expect(screen.getByText(/There is no inspectable Skill Run/)).toBeTruthy();
  fireEvent.keyDown(firstSkill.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(secondSkill.tabIndex).toBe(0);
  expect(firstSkill.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(secondSkill);
  fireEvent.keyDown(secondSkill.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (screen.getByRole("checkbox", { name: /Night notes/i }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(
    screen.getByText("Review Night notes night-notes instructions"),
  ).toBeTruthy();
  fireEvent.keyDown(secondSkill.closest(".agent-choice-list") as HTMLElement, {
    key: "Home",
  });
  expect(firstSkill.tabIndex).toBe(0);
  const firstTool = screen.getByLabelText("Tool memory_search");
  const secondTool = screen.getByLabelText("Tool http_fetch");
  expect(firstTool.tabIndex).toBe(0);
  expect(secondTool.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable tool-selection Run/),
  ).toBeTruthy();
  fireEvent.keyDown(firstTool.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(secondTool.tabIndex).toBe(0);
  expect(document.activeElement).toBe(secondTool);
  fireEvent.keyDown(secondTool.closest(".agent-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (screen.getByRole("checkbox", { name: /HTTP fetch/i }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
it("moves through approval, retry and notice policies without inventing a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
            ? []
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : {
                  id: "draft",
                  name: "Morning review",
                  description: "",
                  goal: "Summarize",
                  system_prompt: "",
                  model: "local",
                  tools: [],
                  search_query: "",
                  fetch_urls: [],
                  skills: [],
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
                  notification_policy: {
                    on_success: false,
                    on_failure: false,
                    on_approval: false,
                  },
                  project_id: null,
                  enabled: false,
                  updated_at: "2026-10-09T12:00:00Z",
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
  const approval = await screen.findByLabelText("Approval require_approval");
  expect(approval.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable approval-policy Run/),
  ).toBeTruthy();
  fireEvent.keyDown(approval.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Require approval before each Run/i,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const none = screen.getByLabelText("Retry none");
  const manual = screen.getByLabelText("Retry manual");
  expect(none.tabIndex).toBe(0);
  expect(manual.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable retry-policy Run/),
  ).toBeTruthy();
  fireEvent.keyDown(none.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(manual.tabIndex).toBe(0);
  expect(document.activeElement).toBe(manual);
  fireEvent.keyDown(manual.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /Manual retry/i }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  const failure = screen.getByLabelText("Notice on_failure");
  const success = screen.getByLabelText("Notice on_success");
  expect(failure.tabIndex).toBe(0);
  expect(success.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable notice-policy Run/),
  ).toBeTruthy();
  fireEvent.keyDown(failure.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(success.tabIndex).toBe(0);
  fireEvent.keyDown(success.closest(".agent-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /When a report succeeds/i,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
it("moves through workflow mode and tool calling without inventing a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
            ? []
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : {
                  id: "draft",
                  name: "Morning review",
                  description: "",
                  goal: "Summarize",
                  system_prompt: "",
                  model: "local",
                  tools: [],
                  search_query: "",
                  fetch_urls: [],
                  skills: [],
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
                  notification_policy: {
                    on_success: false,
                    on_failure: false,
                    on_approval: false,
                  },
                  project_id: null,
                  enabled: false,
                  updated_at: "2026-10-09T12:00:00Z",
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
  const toolCalling = await screen.findByLabelText("Tool calling bounded");
  expect(toolCalling.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable tool-calling-policy Run/),
  ).toBeTruthy();
  fireEvent.keyDown(toolCalling.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Bounded tool calling during the report/i,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const sequential = screen.getByLabelText("Workflow sequential");
  const gated = screen.getByLabelText("Workflow gated");
  expect(sequential.tabIndex).toBe(0);
  expect(gated.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable workflow-mode Run/),
  ).toBeTruthy();
  fireEvent.keyDown(sequential.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(gated.tabIndex).toBe(0);
  expect(sequential.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(gated);
  fireEvent.keyDown(gated.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /Gated/i }) as HTMLInputElement).checked,
  ).toBe(true);
  fireEvent.keyDown(gated.closest(".agent-choice-list") as HTMLElement, {
    key: "Home",
  });
  expect(sequential.tabIndex).toBe(0);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
it("retries a failed workflow from Agents history without Run now", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
            ? []
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : options?.method === "POST" &&
                  String(url).includes("/retry-workflow")
                ? {
                    id: "retry-run",
                    capability: "agent.workflow",
                    status: "queued",
                  }
                : {
                    id: "draft",
                    name: "Morning review",
                    description: "",
                    goal: "Summarize",
                    system_prompt: "",
                    model: "local",
                    tools: [],
                    search_query: "",
                    fetch_urls: [],
                    skills: [],
                    trigger: "manual",
                    cron_expr: "",
                    interval_seconds: null,
                    run_at: null,
                    maximum_runtime: 600,
                    output_expectation: "Report",
                    require_approval: false,
                    workflow_mode: "sequential",
                    tool_calling: "none",
                    retry_policy: { mode: "manual" },
                    notification_policy: {
                      on_success: false,
                      on_failure: false,
                      on_approval: false,
                    },
                    project_id: null,
                    enabled: true,
                    updated_at: "2026-10-11T12:00:00Z",
                    next_run_at: null,
                    last_run_at: "2026-10-11T12:00:00Z",
                    last_status: "failed",
                    failure_count: 1,
                    effective_permissions: [],
                    runs: [
                      {
                        id: "fail-run-dddd",
                        capability: "agent.workflow",
                        status: "failed",
                        created_at: "2026-10-11T12:00:00Z",
                        retry: { allowed: true, retry_run_id: null },
                      },
                    ],
                  },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(
    await screen.findByRole("button", {
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
it("stops an in-progress Run from Agents history without Run now", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
            ? []
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : options?.method === "POST" && String(url).endsWith("/cancel")
                ? { id: "run-live-eeee", status: "cancel_requested" }
                : {
                    id: "draft",
                    name: "Morning review",
                    description: "",
                    goal: "Summarize",
                    system_prompt: "",
                    model: "local",
                    tools: [],
                    search_query: "",
                    fetch_urls: [],
                    skills: [],
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
                    notification_policy: {
                      on_success: false,
                      on_failure: false,
                      on_approval: false,
                    },
                    project_id: null,
                    enabled: true,
                    updated_at: "2026-10-11T12:00:00Z",
                    next_run_at: null,
                    last_run_at: "2026-10-11T12:00:00Z",
                    last_status: "running",
                    failure_count: 0,
                    effective_permissions: [],
                    runs: [
                      {
                        id: "run-live-eeee",
                        capability: "agent.workflow",
                        status: "running",
                        created_at: "2026-10-11T12:00:00Z",
                      },
                    ],
                  },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Stop agent.workflow run-live",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/run-live-eeee/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(screen.getByRole("heading", { name: "Morning review" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("approves a waiting Run from Agents without Run now or the inspector", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
            ? []
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : options?.method === "POST" && String(url).includes("/approval")
                ? { id: "wait-run-cccc", status: "queued" }
                : {
                    id: "draft",
                    name: "Morning review",
                    description: "",
                    goal: "Summarize",
                    system_prompt: "",
                    model: "local",
                    tools: [],
                    search_query: "",
                    fetch_urls: [],
                    skills: [],
                    trigger: "manual",
                    cron_expr: "",
                    interval_seconds: null,
                    run_at: null,
                    maximum_runtime: 600,
                    output_expectation: "Report",
                    require_approval: true,
                    workflow_mode: "sequential",
                    tool_calling: "none",
                    retry_policy: { mode: "none" },
                    notification_policy: {
                      on_success: false,
                      on_failure: false,
                      on_approval: true,
                    },
                    project_id: null,
                    enabled: true,
                    updated_at: "2026-10-11T12:00:00Z",
                    next_run_at: null,
                    last_run_at: "2026-10-11T12:00:00Z",
                    last_status: "waiting_for_approval",
                    failure_count: 0,
                    effective_permissions: [],
                    runs: [
                      {
                        id: "wait-run-cccc",
                        capability: "agent.workflow",
                        status: "waiting_for_approval",
                        created_at: "2026-10-11T12:00:00Z",
                      },
                    ],
                  },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Approve and queue waiting Run wait-run",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/wait-run-cccc/approval",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ resolution: "granted" }),
      }),
    ),
  );
  expect(screen.getByRole("heading", { name: "Morning review" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Stop / })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("shows the latest agent report from Agents without Run now", async () => {
  const agent = {
    id: "draft",
    name: "Morning review",
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: [],
    search_query: "",
    fetch_urls: [],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: null,
    enabled: true,
    updated_at: "2026-10-11T12:00:00Z",
    next_run_at: null,
    last_run_at: "2026-10-11T12:00:00Z",
    last_status: "succeeded",
    failure_count: 0,
    effective_permissions: [],
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
      },
    ],
  };
  const fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/artifacts?")) {
      expect(url).toBe("/api/artifacts?run_id=report-run");
      return {
        ok: true,
        json: async () => [
          {
            id: "report-md",
            type: "markdown",
            mime_type: "text/markdown",
            original_filename: "agent-report.md",
            size_bytes: 40,
            created_at: "2026-10-11T12:00:00Z",
            run_id: "report-run",
            parent_artifact_ids: [],
            metadata: {},
          },
        ],
      };
    }
    if (String(url).endsWith("/artifacts/report-md/file")) {
      return { ok: true, text: async () => "GPU idle." };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
              ? []
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  expect(
    await screen.findByRole("heading", { name: "Agent report" }),
  ).toBeTruthy();
  expect(await screen.findByText("GPU idle.")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Morning review" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("shows recorded search sources next to the latest report from Agents without Run now", async () => {
  const agent = {
    id: "draft",
    name: "Morning review",
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: ["web_search"],
    search_query: "workstation GPU news",
    fetch_urls: [],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: null,
    enabled: true,
    updated_at: "2026-10-11T12:00:00Z",
    next_run_at: null,
    last_run_at: "2026-10-11T12:00:00Z",
    last_status: "succeeded",
    failure_count: 0,
    effective_permissions: [],
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "flow-run",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
        metadata: {
          web_search: {
            query: "workstation GPU news",
            searched_at: "2026-10-11T12:00:00Z",
            partial: false,
            sources: [
              {
                id: 1,
                title: "GPU briefing",
                url: "https://example.com/gpu",
                snippet: "Untrusted excerpt",
              },
            ],
          },
        },
      },
    ],
  };
  const fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/artifacts?")) {
      return {
        ok: true,
        json: async () => [
          {
            id: "report-md",
            type: "markdown",
            mime_type: "text/markdown",
            original_filename: "agent-report.md",
            size_bytes: 12,
            created_at: "2026-10-11T12:00:00Z",
            run_id: "report-run",
            parent_artifact_ids: [],
            metadata: {},
          },
        ],
      };
    }
    if (String(url).endsWith("/artifacts/report-md/file")) {
      return { ok: true, text: async () => "GPU idle." };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
              ? []
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  expect(
    await screen.findByRole("heading", { name: "Agent report" }),
  ).toBeTruthy();
  const source = await screen.findByRole("link", {
    name: "Source GPU briefing 1",
  });
  expect(source.getAttribute("href")).toBe("https://example.com/gpu");
  expect(screen.getByText(/Searched: workstation GPU news/)).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("shows recorded fetched pages next to the latest report from Agents without Run now", async () => {
  const agent = {
    id: "draft",
    name: "Morning review",
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: ["http_fetch"],
    search_query: "",
    fetch_urls: ["https://www.example.com/"],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: null,
    enabled: true,
    updated_at: "2026-10-11T12:00:00Z",
    next_run_at: null,
    last_run_at: "2026-10-11T12:00:00Z",
    last_status: "succeeded",
    failure_count: 0,
    effective_permissions: [],
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "flow-run",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
        metadata: {
          http_fetch: {
            urls: ["https://www.example.com/"],
            fetched_at: "2026-10-11T12:00:00Z",
            pages: [
              {
                url: "https://www.example.com/",
                status: 200,
                text: "<script>alert(1)</script>Public excerpt",
                untrusted: true,
              },
            ],
          },
        },
      },
    ],
  };
  const fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/artifacts?")) {
      return {
        ok: true,
        json: async () => [
          {
            id: "report-md",
            type: "markdown",
            mime_type: "text/markdown",
            original_filename: "agent-report.md",
            size_bytes: 12,
            created_at: "2026-10-11T12:00:00Z",
            run_id: "report-run",
            parent_artifact_ids: [],
            metadata: {},
          },
        ],
      };
    }
    if (String(url).endsWith("/artifacts/report-md/file")) {
      return { ok: true, text: async () => "GPU idle." };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
              ? []
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  expect(
    await screen.findByRole("heading", { name: "Agent report" }),
  ).toBeTruthy();
  const page = await screen.findByRole("link", {
    name: "Page https://www.example.com/",
  });
  expect(page.getAttribute("href")).toBe("https://www.example.com/");
  expect(screen.getByText("HTML/text excerpt stored")).toBeTruthy();
  expect(screen.queryByText("Public excerpt")).toBeNull();
  expect(document.querySelector("script")).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("shows recorded registry tool calls next to the latest report from Agents without Run now", async () => {
  const agent = {
    id: "draft",
    name: "Morning review",
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: ["telemetry"],
    search_query: "",
    fetch_urls: [],
    skills: [],
    trigger: "manual",
    cron_expr: "",
    interval_seconds: null,
    run_at: null,
    maximum_runtime: 600,
    output_expectation: "Report",
    require_approval: false,
    workflow_mode: "sequential",
    tool_calling: "bounded",
    retry_policy: { mode: "none" },
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: null,
    enabled: true,
    updated_at: "2026-10-11T12:00:00Z",
    next_run_at: null,
    last_run_at: "2026-10-11T12:00:00Z",
    last_status: "succeeded",
    failure_count: 0,
    effective_permissions: [],
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "flow-run",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
        metadata: {
          tool_calls: [
            {
              id: "call-0-0",
              tool: "system_snapshot",
              arguments: {},
              round: 0,
            },
          ],
        },
      },
    ],
  };
  const fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/artifacts?")) {
      return {
        ok: true,
        json: async () => [
          {
            id: "report-md",
            type: "markdown",
            mime_type: "text/markdown",
            original_filename: "agent-report.md",
            size_bytes: 12,
            created_at: "2026-10-11T12:00:00Z",
            run_id: "report-run",
            parent_artifact_ids: [],
            metadata: {},
          },
        ],
      };
    }
    if (String(url).endsWith("/artifacts/report-md/file")) {
      return { ok: true, text: async () => "GPU idle." };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/provider")
            ? { models: ["local"], default_model: "local" }
            : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
              ? []
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : agent,
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount(true);
  expect(
    await screen.findByRole("heading", { name: "Registry tool calls" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("Call system_snapshot call-0-0")).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
it("shows last-parent workflow steps next to history from Agents without Run now", async () => {
  const agent = {
    id: "draft",
    name: "Morning review",
    description: "",
    goal: "Summarize",
    system_prompt: "",
    model: "local",
    tools: ["telemetry"],
    search_query: "",
    fetch_urls: [],
    skills: [],
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
    notification_policy: {
      on_success: false,
      on_failure: false,
      on_approval: false,
    },
    project_id: null,
    enabled: true,
    updated_at: "2026-10-11T12:00:00Z",
    next_run_at: null,
    last_run_at: "2026-10-11T12:00:00Z",
    last_status: "succeeded",
    failure_count: 0,
    effective_permissions: [],
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "flow-run",
        status: "succeeded",
        created_at: "2026-10-11T12:01:00Z",
      },
      {
        id: "flow-run",
        capability: "agent.workflow",
        executor_type: "agent_workflow",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
        workflow: {
          parent_run_id: "flow-run",
          mode: "sequential",
          steps: [
            {
              run_id: "step-search",
              key: "memory_search",
              gate: "none",
              status: "succeeded",
              capability: "agent.step",
              memory_id: "memory-1",
            },
            {
              run_id: "step-report",
              key: "report",
              gate: "none",
              status: "succeeded",
              capability: "agent.execute",
            },
          ],
        },
      },
      {
        id: "old-flow",
        capability: "agent.workflow",
        executor_type: "agent_workflow",
        status: "succeeded",
        created_at: "2026-10-10T12:00:00Z",
        workflow: {
          parent_run_id: "old-flow",
          mode: "gated",
          steps: [
            {
              run_id: "old-step",
              key: "system_snapshot",
              gate: "none",
              status: "succeeded",
              capability: "agent.step",
            },
          ],
        },
      },
    ],
  };
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("/llama")
        ? { models: [], instances: [] }
        : url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.includes("/skills") || url.includes("/projects") || url.endsWith("tools")
            ? []
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : url.includes("/artifacts")
                ? []
                : agent,
  }));
  vi.stubGlobal("fetch", fetch);
  mount(true);
  expect(
    await screen.findByRole("heading", { name: "Workflow steps" }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect step memory_search step-sea" })
      .getAttribute("href"),
  ).toBe("/runs/step-search");
  expect(
    screen
      .getByRole("link", { name: "Inspect step report step-rep" })
      .getAttribute("href"),
  ).toBe("/runs/step-report");
  expect(
    screen.queryByRole("link", { name: /Inspect step system_snapshot/ }),
  ).toBeNull();
  expect(
    screen
      .getByRole("link", {
        name: "View saved observation memory_search memory-1",
      })
      .getAttribute("href"),
  ).toBe("/memory/memory-1");
  expect(
    screen.getByRole("region", { name: "Workflow steps" }).textContent,
  ).toMatch(/Stop stays on execution history/);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
