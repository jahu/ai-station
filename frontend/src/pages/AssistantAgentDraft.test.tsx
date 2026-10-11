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
  tools: ["system_snapshot", "web_search"],
  skills: ["station-briefing"],
  trigger: "cron",
  cron_expr: "0 7 * * 1-5",
  require_approval: true,
  workflow_mode: "gated",
  search_query: "workstation GPU news",
  fetch_urls: [] as string[],
  last_status: "",
  last_run_at: null as string | null,
  next_run_at: null as string | null,
  retry_policy: { mode: "none" as string },
  notification_policy: {
    on_success: false,
    on_failure: false,
    on_approval: false,
  },
  runs: [] as {
    id: string;
    capability: string;
    status: string;
    created_at: string;
    executor_type?: string;
    parent_run_id?: string;
    parameters?: { tool?: string };
    retry?: { allowed: boolean; retry_run_id?: string | null };
    metadata?: Record<string, unknown>;
    workflow?: {
      parent_run_id: string;
      mode: string;
      tool_calling?: string;
      steps: {
        run_id: string;
        key: string;
        gate: string;
        status: string;
        capability: string;
        tool_calls?: {
          id: string;
          tool: string;
          arguments: Record<string, unknown>;
          round: number;
        }[];
        memory_id?: string | null;
      }[];
    };
  }[],
};

function stationCatalog(path: string) {
  if (String(path).endsWith("/llama")) return { models: [], instances: [] };
  if (String(path).endsWith("/hardware")) return { gpus: [] };
  if (String(path).endsWith("/chat/provider")) {
    return { models: ["local-27b", "qwen3:8b"], default_model: "local-27b" };
  }
  return null;
}

function withCatalog(
  handler: (
    path: string,
    options?: RequestInit,
  ) => Promise<{
    ok: boolean;
    json?: () => Promise<unknown>;
    text?: () => Promise<string>;
  }>,
) {
  return async (path: string, options?: RequestInit) => {
    const catalog = stationCatalog(path);
    if (catalog) return { ok: true, json: async () => catalog };
    return handler(path, options);
  };
}

function mount(agent = draft) {
  let current = { ...agent };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    const url = String(path);
    const catalog = stationCatalog(url);
    if (catalog) return { ok: true, json: async () => catalog };
    if (options?.method === "PUT" && url.endsWith(`/agents/${current.id}`)) {
      current = {
        ...current,
        ...JSON.parse(String(options.body)),
        updated_at: "2026-10-11T10:02:00Z",
      };
      return { ok: true, json: async () => current };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/enabled")
          ? { ...current, enabled: true, updated_at: "2026-10-11T10:01:00Z" }
          : url.endsWith("/duplicate")
            ? {
                ...current,
                id: "agent-copy",
                name: `${current.name} (copy)`,
                enabled: false,
                last_run_at: null,
                next_run_at: null,
                last_status: "",
                runs: [],
              }
            : url.endsWith("/run") && options?.method === "POST"
              ? {
                  id: "queued-run-ffff",
                  capability: "agent.workflow",
                  status: "queued",
                }
              : url.includes("/artifacts")
              ? []
              : url.includes("/skills")
                ? [
                    {
                      id: "station-briefing",
                      name: "Station briefing",
                      version: "1.0.0",
                      description: "Local status report format",
                      required_permissions: [],
                      instructions:
                        "Always mention GPU memory when it appears.",
                    },
                    {
                      id: "daily-brief",
                      name: "Daily brief",
                      version: "1.2.0",
                      description: "Morning format",
                      required_permissions: [],
                      instructions: "Cite only supplied tool results.",
                    },
                  ]
                : url.endsWith("/tools")
                  ? [
                      {
                        name: "system_snapshot",
                        description:
                          "Read current host hardware telemetry through the Host Runner.",
                        operational: true,
                        required_permissions: ["filesystem_read"],
                      },
                      {
                        name: "web_search",
                        description:
                          "Search public pages through the configured search service.",
                        operational: true,
                        required_permissions: ["network_read"],
                      },
                      {
                        name: "http_fetch",
                        description: "GET reviewed public pages.",
                        operational: true,
                        required_permissions: ["network_read"],
                      },
                      {
                        name: "browser",
                        description:
                          "Browser automation is not implemented for agents.",
                        operational: false,
                        required_permissions: [],
                      },
                    ]
                  : url.includes("/retry-workflow")
                    ? {
                        id: "retry-run",
                        capability: "agent.workflow",
                        status: "queued",
                        retry: {
                          allowed: false,
                          retry_of: "fail-run-dddd",
                        },
                      }
                    : url.endsWith("/cancel") && options?.method === "POST"
                      ? { id: "run-live-eeee", status: "cancel_requested" }
                      : url.includes("/approval") && options?.method === "POST"
                        ? {
                            id: "wait-run-cccc",
                            status:
                              JSON.parse(String(options.body)).resolution ===
                              "denied"
                                ? "canceled"
                                : "queued",
                          }
                        : current,
    };
  });
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

it("reviews attached tools from the conversation without inventing a Run", async () => {
  const fetch = mount({
    ...draft,
    tools: ["web_search", "browser", "missing"],
  });
  expect(
    await screen.findByText(
      "Search public pages through the configured search service. network_read",
    ),
  ).toBeTruthy();
  expect(screen.getByLabelText("Tool web_search")).toBeTruthy();
  expect(screen.getByLabelText("Tool browser")).toBeTruthy();
  expect(screen.getByText(/— Unavailable/)).toBeTruthy();
  expect(screen.getByLabelText("Tool missing")).toBeTruthy();
  expect(screen.getByText("Not in the tool registry.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("reviews attached skill instructions from the conversation without inventing a Run", async () => {
  const fetch = mount();
  expect(await screen.findByText("Station briefing")).toBeTruthy();
  fireEvent.click(
    await screen.findByText(
      "Review Station briefing station-briefing instructions",
    ),
  );
  expect(
    screen.getByText("Always mention GPU memory when it appears."),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: "Remove skill station-briefing agent-on",
    }),
  ).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("keeps Enable disabled when a saved skill is missing from the catalog", async () => {
  const fetch = mount({
    ...draft,
    tools: ["system_snapshot"],
    search_query: "",
    skills: ["gone-skill"],
  });
  expect(
    await screen.findByText("Missing skills prevent activation: gone-skill."),
  ).toBeTruthy();
  expect(screen.getByText("Not in the installed catalog.")).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
});

it("removes a missing skill from the conversation definition without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    tools: ["system_snapshot"],
    search_query: "",
    skills: ["gone-skill"],
  });
  expect(
    await screen.findByText("Missing skills prevent activation: gone-skill."),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Remove skill gone-skill agent-on",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    skills: [],
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition agent-on",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("shows saved notice policy from the conversation without inventing a Run", async () => {
  const fetch = mount({
    ...draft,
    notification_policy: {
      on_failure: true,
      on_success: false,
      on_approval: true,
    },
  });
  expect(
    await screen.findByText(
      "In-app notices on failure or interruption, waiting for approval",
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/In-app notices on.*success/)).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("inspects the saved definition without queueing Run now", async () => {
  const fetch = mount();
  expect(await screen.findByText("0 7 * * 1-5 (UTC)")).toBeTruthy();
  expect(
    await screen.findByText(
      "Read current host hardware telemetry through the Host Runner. filesystem_read",
    ),
  ).toBeTruthy();
  expect(screen.getByLabelText("Tool system_snapshot")).toBeTruthy();
  expect(screen.getByLabelText("Tool web_search")).toBeTruthy();
  expect(
    screen.getByText("Summarize GPU telemetry every weekday."),
  ).toBeTruthy();
  expect(
    screen.getByText(
      "No executions yet. Run now queues a new workflow from the saved definition.",
    ),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Run now agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.queryByRole("region", { name: "Execution history" }),
  ).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "Inspect agent memory agent-on" })
      .getAttribute("href"),
  ).toBe("/memory?scope=agent&scope_id=agent-one");
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
  expect(await screen.findByLabelText("Tool system_snapshot")).toBeTruthy();
  expect(screen.getByLabelText("Tool web_search")).toBeTruthy();
  expect(
    await screen.findByLabelText("Skill Station briefing station-briefing"),
  ).toBeTruthy();
  expect(
    (screen.getByLabelText("Public search query agent-on") as HTMLInputElement)
      .value,
  ).toBe("workstation GPU news");
  expect(screen.getByText("Required before each Run")).toBeTruthy();
  expect(screen.getByText("Gated")).toBeTruthy();
  expect(
    screen.getByText("Summarize GPU telemetry every weekday."),
  ).toBeTruthy();
  expect(screen.getByText(/does not invent a conversation Run/)).toBeTruthy();
  expect(
    screen.getByText(
      /Run now queues a new workflow from that saved definition/,
    ),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Run now agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
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

it("keeps Enable disabled when an attached tool is unavailable", async () => {
  const fetch = mount({ ...draft, tools: ["browser"] });
  expect(await screen.findByText(/— Unavailable/)).toBeTruthy();
  const enable = screen.getByRole("button", {
    name: "Enable saved definition agent-on",
  });
  expect((enable as HTMLButtonElement).disabled).toBe(true);
  expect(
    screen.getByText("Unavailable tools prevent activation: browser."),
  ).toBeTruthy();
  fireEvent.click(enable);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Duplicate as draft agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});

it("keeps Enable disabled when a saved tool is missing from the registry", async () => {
  const fetch = mount({ ...draft, tools: ["invented_shell"] });
  expect(await screen.findByText("Not in the tool registry.")).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    await screen.findByText(
      "Unavailable tools prevent activation: invented_shell.",
    ),
  ).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
});

it("removes an unavailable tool from the conversation definition without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    tools: ["system_snapshot", "browser"],
    search_query: "",
  });
  expect(
    await screen.findByText("Unavailable tools prevent activation: browser."),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.queryByRole("button", {
      name: "Remove tool system_snapshot agent-on",
    }),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Remove tool browser agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    tools: ["system_snapshot"],
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition agent-on",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("removes a tool missing from the registry without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    tools: ["system_snapshot", "invented_shell"],
    search_query: "",
  });
  expect(
    await screen.findByText(
      "Unavailable tools prevent activation: invented_shell.",
    ),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Remove tool invented_shell agent-on",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    tools: ["system_snapshot"],
    enabled: false,
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition agent-on",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("attaches an installed skill from the conversation without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    tools: ["system_snapshot"],
    search_query: "",
    skills: ["station-briefing"],
  });
  expect(
    await screen.findByRole("button", {
      name: "Add skill daily-brief agent-on",
    }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: "Add skill station-briefing agent-on",
    }),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Add skill daily-brief agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    skills: ["station-briefing", "daily-brief"],
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
  });
  expect(
    await screen.findByLabelText("Skill Daily brief daily-brief"),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("attaches an operational registry tool from the conversation without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    tools: ["system_snapshot"],
    search_query: "",
  });
  expect(
    await screen.findByRole("button", {
      name: "Add tool http_fetch agent-on",
    }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Add tool web_search agent-on" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Add tool browser agent-on" }),
  ).toBeNull();
  expect(screen.getByLabelText("Tool browser")).toBeTruthy();
  expect(screen.queryByLabelText("Reviewed URLs agent-on")).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Add tool http_fetch agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    tools: ["system_snapshot", "http_fetch"],
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
  });
  expect(
    await screen.findByLabelText("Reviewed URLs agent-on"),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByText(
      "http_fetch needs reviewed public URLs before activation.",
    ),
  ).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("keeps Enable disabled when web_search has no public query", async () => {
  mount({ ...draft, search_query: "" });
  expect(await screen.findByLabelText("Tool web_search")).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByText(
      "web_search needs a public search query before activation.",
    ),
  ).toBeTruthy();
  expect(
    (screen.getByLabelText("Public search query agent-on") as HTMLInputElement)
      .value,
  ).toBe("");
});

it("saves a public search query from the conversation without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    search_query: "",
    tools: ["web_search"],
  });
  expect(
    await screen.findByText(
      "web_search needs a public search query before activation.",
    ),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Public search query agent-on"), {
    target: { value: "open weight language models" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save public search query agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    search_query: "open weight language models",
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
    tools: ["web_search"],
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition agent-on",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("keeps Enable disabled when http_fetch has no reviewed URLs", async () => {
  mount({ ...draft, tools: ["http_fetch"], fetch_urls: [] });
  expect(await screen.findByLabelText("Tool http_fetch")).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByText(
      "http_fetch needs reviewed public URLs before activation.",
    ),
  ).toBeTruthy();
  expect(
    (screen.getByLabelText("Reviewed URLs agent-on") as HTMLTextAreaElement)
      .value,
  ).toBe("");
});

it("saves reviewed fetch URLs from the conversation without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    tools: ["http_fetch"],
    fetch_urls: [],
    search_query: "",
  });
  expect(
    await screen.findByText(
      "http_fetch needs reviewed public URLs before activation.",
    ),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Reviewed URLs agent-on"), {
    target: { value: "https://www.example.com/" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save reviewed URLs agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    fetch_urls: ["https://www.example.com/"],
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
    tools: ["http_fetch"],
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition agent-on",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("keeps Enable disabled when the saved definition has no model", async () => {
  mount({ ...draft, model: "" });
  expect(await screen.findByText("Morning briefing")).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByText("Select a local model before enabling."),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Saved model agent-on" }),
  ).toBeTruthy();
});

it("saves a local model on the conversation definition without Enable or Run now", async () => {
  const fetch = mount({
    ...draft,
    model: "",
    tools: ["system_snapshot"],
    search_query: "",
  });
  expect(
    await screen.findByText("Select a local model before enabling."),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Enable saved definition agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Saved model agent-on" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "qwen3:8b, local server" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Use model" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
  const write = fetch.mock.calls.find((call) => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(write[1]?.body))).toMatchObject({
    model: "qwen3:8b",
    enabled: false,
    expected_updated_at: "2026-10-11T10:00:00Z",
    tools: ["system_snapshot"],
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Enable saved definition agent-on",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("queues Run now from the conversation without opening the inspector", async () => {
  const fetch = mount({ ...draft, enabled: true });
  const button = await screen.findByRole("button", {
    name: "Run now agent-on",
  });
  expect((button as HTMLButtonElement).disabled).toBe(false);
  expect(screen.getByText("Morning briefing")).toBeTruthy();
  expect(screen.getByText(/Enabled/)).toBeTruthy();
  fireEvent.click(button);
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
        }),
      }),
    ),
  );
  expect(screen.getByText("Morning briefing")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every(
      (call) => !String(call[0]).includes("/runs/queued-run"),
    ),
  ).toBe(true);
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
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Stop / })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Agent report" })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/artifacts")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("stops an in-progress Run from conversation history without Run now", async () => {
  const fetch = mount({
    ...draft,
    enabled: true,
    last_status: "running",
    last_run_at: "2026-10-11T12:00:00Z",
    runs: [
      {
        id: "run-live-eeee",
        capability: "agent.workflow",
        status: "running",
        created_at: "2026-10-11T12:00:00Z",
      },
    ],
  });
  expect(
    (
      (await screen.findByRole("button", {
        name: "Run now agent-on",
      })) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Stop agent.workflow run-live",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/run-live-eeee/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(screen.getByText("Morning briefing")).toBeTruthy();
});

it("approves a waiting Run from the conversation without Run now or the inspector", async () => {
  const waiting = {
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
  };
  const fetch = mount(waiting);
  expect(
    (
      await screen.findByRole("link", { name: "Review waiting Run wait-run" })
    ).getAttribute("href"),
  ).toBe("/runs/wait-run-cccc");
  expect(
    (
      screen.getByRole("button", {
        name: "Run now agent-on",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", {
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
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Stop / })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(screen.getByText("Morning briefing")).toBeTruthy();
});

it("denies a waiting Run from conversation history without Run now", async () => {
  const fetch = mount({
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
      (await screen.findByRole("button", {
        name: "Run now agent-on",
      })) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Deny agent.workflow wait-run",
    }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/wait-run-cccc/approval",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ resolution: "denied" }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("pauses an enabled agent from the conversation without starting a Run", async () => {
  const enabled = { ...draft, enabled: true };
  const fetch = vi.fn(
    withCatalog(async (path: string) => ({
      ok: true,
      json: async () =>
        String(path).endsWith("/enabled")
          ? { ...enabled, enabled: false }
          : enabled,
    })),
  );
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
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
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
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
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

it("shows the latest agent report in the conversation without Run now", async () => {
  const agent = {
    ...draft,
    enabled: true,
    last_status: "succeeded",
    last_run_at: "2026-10-11T12:00:00Z",
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
      },
      {
        id: "flow-run",
        capability: "agent.workflow",
        executor_type: "agent_workflow",
        status: "succeeded",
        created_at: "2026-10-11T11:59:00Z",
      },
    ],
  };
  const fetch = vi.fn(
    withCatalog(async (path: string) => {
      if (String(path).includes("/artifacts?")) {
        expect(path).toBe("/api/artifacts?run_id=report-run");
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
              metadata: { partial: false },
            },
          ],
        };
      }
      if (String(path).endsWith("/artifacts/report-md/file")) {
        return {
          ok: true,
          text: async () => "## Morning briefing\n\nGPU idle.",
        };
      }
      return { ok: true, json: async () => agent };
    }),
  );
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
  expect(
    await screen.findByRole("heading", { name: "Agent report" }),
  ).toBeTruthy();
  expect(await screen.findByText("GPU idle.")).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "Morning briefing" }),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("shows recorded search sources next to the latest report without Run now", async () => {
  const agent = {
    ...draft,
    enabled: true,
    last_status: "succeeded",
    last_run_at: "2026-10-11T12:00:00Z",
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
      {
        id: "old-search",
        capability: "agent.step",
        executor_type: "agent_tool",
        parent_run_id: "old-flow",
        status: "succeeded",
        created_at: "2026-10-10T12:00:00Z",
        parameters: { tool: "web_search" },
        metadata: {
          web_search: {
            query: "stale query",
            searched_at: "2026-10-10T12:00:00Z",
            partial: false,
            sources: [
              {
                id: 1,
                title: "Stale source",
                url: "https://example.com/stale",
                snippet: "Older excerpt",
              },
            ],
          },
        },
      },
    ],
  };
  const fetch = vi.fn(
    withCatalog(async (path: string) => {
      if (String(path).includes("/artifacts?")) {
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
      if (String(path).endsWith("/artifacts/report-md/file")) {
        return { ok: true, text: async () => "GPU idle." };
      }
      return { ok: true, json: async () => agent };
    }),
  );
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
  expect(
    await screen.findByRole("heading", { name: "Agent report" }),
  ).toBeTruthy();
  const source = await screen.findByRole("link", {
    name: "Source GPU briefing 1",
  });
  expect(source.getAttribute("href")).toBe("https://example.com/gpu");
  expect(screen.getByText(/Searched: workstation GPU news/)).toBeTruthy();
  expect(screen.queryByRole("link", { name: /Stale source/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("uses the latest report's search sibling when the report has not copied sources yet", async () => {
  const agent = {
    ...draft,
    enabled: true,
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "flow-run",
        status: "running",
        created_at: "2026-10-11T12:01:00Z",
      },
      {
        id: "search-run",
        capability: "agent.step",
        executor_type: "agent_tool",
        parent_run_id: "flow-run",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
        parameters: { tool: "web_search" },
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
  const fetch = vi.fn(
    withCatalog(async (path: string) => {
      if (String(path).includes("/artifacts?")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true, json: async () => agent };
    }),
  );
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
  const source = await screen.findByRole("link", {
    name: "Source GPU briefing 1",
  });
  expect(source.getAttribute("href")).toBe("https://example.com/gpu");
  expect(screen.queryByRole("heading", { name: "Agent report" })).toBeNull();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
});

it("shows recorded fetched pages next to the latest report without Run now", async () => {
  const agent = {
    ...draft,
    enabled: true,
    last_status: "succeeded",
    last_run_at: "2026-10-11T12:00:00Z",
    fetch_urls: ["https://www.example.com/"],
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
      {
        id: "old-fetch",
        capability: "agent.step",
        executor_type: "agent_tool",
        parent_run_id: "old-flow",
        status: "succeeded",
        created_at: "2026-10-10T12:00:00Z",
        parameters: { tool: "http_fetch" },
        metadata: {
          http_fetch: {
            urls: ["https://example.com/stale"],
            fetched_at: "2026-10-10T12:00:00Z",
            pages: [
              {
                url: "https://example.com/stale",
                status: 200,
                text: "Older excerpt",
                untrusted: true,
              },
            ],
          },
        },
      },
    ],
  };
  const fetch = vi.fn(
    withCatalog(async (path: string) => {
      if (String(path).includes("/artifacts?")) {
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
      if (String(path).endsWith("/artifacts/report-md/file")) {
        return { ok: true, text: async () => "GPU idle." };
      }
      return { ok: true, json: async () => agent };
    }),
  );
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
  expect(
    await screen.findByRole("heading", { name: "Agent report" }),
  ).toBeTruthy();
  const page = await screen.findByRole("link", {
    name: "Page https://www.example.com/",
  });
  expect(page.getAttribute("href")).toBe("https://www.example.com/");
  expect(screen.getByText("HTML/text excerpt stored")).toBeTruthy();
  expect(screen.queryByText("Public excerpt")).toBeNull();
  expect(screen.queryByRole("link", { name: /stale/ })).toBeNull();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("uses the latest report's fetch sibling when the report has not copied pages yet", async () => {
  const agent = {
    ...draft,
    enabled: true,
    runs: [
      {
        id: "report-run",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "flow-run",
        status: "running",
        created_at: "2026-10-11T12:01:00Z",
      },
      {
        id: "fetch-run",
        capability: "agent.step",
        executor_type: "agent_tool",
        parent_run_id: "flow-run",
        status: "succeeded",
        created_at: "2026-10-11T12:00:00Z",
        parameters: { tool: "http_fetch" },
        metadata: {
          http_fetch: {
            urls: ["https://www.example.com/"],
            fetched_at: "2026-10-11T12:00:00Z",
            pages: [
              {
                url: "https://www.example.com/",
                status: 200,
                text: "Public excerpt",
                untrusted: true,
              },
            ],
          },
        },
      },
    ],
  };
  const fetch = vi.fn(
    withCatalog(async (path: string) => {
      if (String(path).includes("/artifacts?")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true, json: async () => agent };
    }),
  );
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
  const page = await screen.findByRole("link", {
    name: "Page https://www.example.com/",
  });
  expect(page.getAttribute("href")).toBe("https://www.example.com/");
  expect(screen.queryByText("Public excerpt")).toBeNull();
  expect(screen.queryByRole("heading", { name: "Agent report" })).toBeNull();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
});

it("shows recorded registry tool calls next to the latest report without Run now", async () => {
  const agent = {
    ...draft,
    enabled: true,
    last_status: "succeeded",
    last_run_at: "2026-10-11T12:00:00Z",
    tool_calling: "bounded",
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
      {
        id: "old-report",
        capability: "agent.report",
        executor_type: "agent",
        parent_run_id: "old-flow",
        status: "succeeded",
        created_at: "2026-10-10T12:00:00Z",
        metadata: {
          tool_calls: [
            {
              id: "call-old",
              tool: "memory_search",
              arguments: { query: "stale" },
              round: 0,
            },
          ],
        },
      },
    ],
  };
  const fetch = vi.fn(
    withCatalog(async (path: string) => {
      if (String(path).includes("/artifacts?")) {
        expect(path).toBe("/api/artifacts?run_id=report-run");
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
      if (String(path).endsWith("/artifacts/report-md/file")) {
        return { ok: true, text: async () => "GPU idle." };
      }
      return { ok: true, json: async () => agent };
    }),
  );
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
  expect(
    await screen.findByRole("heading", { name: "Registry tool calls" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("Call system_snapshot call-0-0")).toBeTruthy();
  expect(screen.queryByLabelText(/memory_search/)).toBeNull();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("shows last-parent workflow steps next to history without Run now", async () => {
  const fetch = mount({
    ...draft,
    enabled: true,
    last_status: "succeeded",
    last_run_at: "2026-10-11T12:00:00Z",
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
          tool_calling: "bounded",
          steps: [
            {
              run_id: "step-search",
              key: "memory_search",
              gate: "none",
              status: "succeeded",
              capability: "agent.step",
            },
            {
              run_id: "step-report",
              key: "report",
              gate: "none",
              status: "succeeded",
              capability: "agent.execute",
              memory_id: "memory-1",
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
  });
  expect(
    await screen.findByRole("heading", { name: "Workflow steps" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("region", { name: "Execution history" }),
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
    screen
      .getByRole("link", { name: "View saved observation report memory-1" })
      .getAttribute("href"),
  ).toBe("/memory/memory-1");
  expect(
    screen.queryByRole("link", { name: /Inspect step system_snapshot/ }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: "Run now agent-on" })).toBeTruthy();
  expect(
    screen.getByRole("region", { name: "Workflow steps" }).textContent,
  ).toMatch(/Stop stays on execution history/);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
