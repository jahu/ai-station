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
import AgentVideoSetup from "./AgentVideoSetup";
import { AssistantAgentDraft } from "./AssistantAgentDraft";
import type { AgentMediaScope } from "./agent-media";

const video = {
  kind: "video" as const,
  description_source: "fixed" as const,
  request: {
    prompt: "Quiet coast",
    duration_seconds: 15,
    composition_mode: "continuous" as const,
    width: 1280,
    height: 704,
    steps: 20,
    seed: 9381,
    gpu: "auto",
  },
};
const capability = {
  available: true,
  recommended_memory_profile: "bounded_11g",
  memory_profiles: [{ id: "bounded_11g", available: true }],
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function frame(children: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function mount(
  value: AgentMediaScope = video,
  maximum = 600,
  disabled = false,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => capability })),
  );
  const apply = vi.fn();
  frame(
    <AgentVideoSetup
      value={value}
      maximumRuntime={maximum}
      disabled={disabled}
      onApply={apply}
    />,
  );
  return apply;
}

it("requires an operator action and preserves the reviewed scene while suggesting a usable allowance", async () => {
  const apply = mount();
  const button = await screen.findByRole("button", {
    name: "Use suggested setup",
  });
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(apply).toHaveBeenCalledWith({
    maximum_runtime: 7200,
    media: {
      ...video,
      request: { ...video.request, memory_profile: "bounded_11g" },
    },
  });
  expect(Object.keys(apply.mock.calls[0][0]).sort()).toEqual([
    "maximum_runtime",
    "media",
  ]);
});

it("keeps a larger custom allowance exact", async () => {
  const apply = mount(video, 9107);
  fireEvent.click(
    await screen.findByRole("button", { name: "Use suggested setup" }),
  );
  expect(apply.mock.calls[0][0].maximum_runtime).toBe(9107);
});

it("uses the existing four-hour ceiling for longer films", async () => {
  const apply = mount({
    ...video,
    request: { ...video.request, duration_seconds: 30 },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Use suggested setup" }),
  );
  expect(apply.mock.calls[0][0].maximum_runtime).toBe(14400);
});

it("does not present setup as ready when the video engine is unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ available: false }) })),
  );
  const apply = vi.fn();
  frame(<AgentVideoSetup value={video} maximumRuntime={600} onApply={apply} />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(
    screen.queryByRole("region", { name: "Suggested video setup" }),
  ).toBeNull();
  expect(apply).not.toHaveBeenCalled();
});

it.each([
  { ...video.request, width: 704, height: 1280 },
  { ...video.request, steps: 4 },
  { ...video.request, image_artifact_id: "reviewed-photo" },
])(
  "preserves explicit incompatible formats, sampling and image scope",
  async (request) => {
    const scope = { ...video, request };
    const apply = mount(scope);
    fireEvent.click(
      await screen.findByRole("button", { name: "Use suggested setup" }),
    );
    expect(apply).toHaveBeenCalledWith({ maximum_runtime: 7200, media: scope });
  },
);

it("cannot apply while an agent is active or a save is pending", async () => {
  const apply = mount(video, 600, true);
  const button = await screen.findByRole("button", {
    name: "Use suggested setup",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(button);
  expect(apply).not.toHaveBeenCalled();
});

it("does not propose another edit when the reviewed setup already has sufficient allowance", async () => {
  mount(
    { ...video, request: { ...video.request, memory_profile: "bounded_11g" } },
    7200,
  );
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(
    screen.queryByRole("region", { name: "Suggested video setup" }),
  ).toBeNull();
});

it("saves a compact conversation draft through one versioned settings update without enabling or running it", async () => {
  let agent = {
    id: "video-draft",
    name: "Coast film",
    goal: "Create the reviewed coastal film",
    description: "",
    model: "fixture-model",
    enabled: false,
    updated_at: "2026-10-24T07:00:00Z",
    tools: ["create_media"],
    media: video,
    maximum_runtime: 600,
    skills: [],
    fetch_urls: [],
    trigger: "manual",
    runs: [],
  };
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        writes.push({ url, body });
        agent = { ...agent, ...body, updated_at: "2026-10-24T07:01:00Z" };
      }
      return {
        ok: true,
        json: async () =>
          url.endsWith("/video/capabilities")
            ? capability
            : url.endsWith("/agents/video-draft")
              ? agent
              : url.endsWith("/chat/provider")
                ? { models: ["fixture-model"], default_model: "fixture-model" }
                : url.endsWith("/agents/tools")
                  ? [
                      {
                        name: "create_media",
                        operational: true,
                        required_permissions: [
                          "filesystem_read",
                          "workspace_write",
                        ],
                      },
                    ]
                  : [],
      };
    }),
  );
  frame(<AssistantAgentDraft agentId="video-draft" compact />);
  const button = await screen.findByRole("button", {
    name: "Apply and save setup",
  });
  expect(writes).toHaveLength(0);
  fireEvent.click(button);
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    url: "/api/agents/video-draft",
    body: {
      expected_updated_at: "2026-10-24T07:00:00Z",
      enabled: false,
      maximum_runtime: 7200,
      tools: ["create_media"],
      media: {
        ...video,
        request: { ...video.request, memory_profile: "bounded_11g" },
      },
    },
  });
  expect(screen.getByRole("link", { name: "Review & enable" })).toBeTruthy();
});
