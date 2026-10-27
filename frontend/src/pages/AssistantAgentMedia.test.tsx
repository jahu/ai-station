import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { AssistantAgentDraft } from "./AssistantAgentDraft";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mountMedia(latestPending = false) {
  const agent = {
    id: "image-agent",
    name: "Garden image",
    goal: "A green garden",
    model: "",
    enabled: true,
    updated_at: "2026-10-27T05:00:00Z",
    tools: ["create_media"],
    trigger: "manual",
    media: {
      kind: "image",
      description_source: "fixed",
      request: { mode: "t2i", backend: "qwen", prompt: "A green garden" },
    },
    runs: [
      ...(latestPending
        ? [
            {
              id: "new-prep",
              task_id: "new-task",
              executor_type: "agent_media",
              capability: "agent.media",
              status: "running",
              parameters: {},
              metadata: {},
            },
          ]
        : []),
      {
        id: "photo",
        task_id: "image-task",
        executor_type: "photo_pipe",
        capability: "image.generate",
        status: "succeeded",
        parameters: {},
        metadata: {},
      },
    ],
  };
  const fetch = vi.fn(async (path: string, _options?: RequestInit) => ({
    ok: true,
    json: async () =>
      path.includes("/artifacts?run_id=photo")
        ? [
            {
              id: "garden",
              type: "image",
              mime_type: "image/png",
              run_id: "photo",
              metadata: {},
              parent_artifact_ids: [],
            },
          ]
        : path.endsWith("/lineage")
          ? { id: "garden", sources: [], derived: [] }
          : path.endsWith("/hardware")
            ? { gpus: [] }
            : path.endsWith("/chat/provider")
              ? { models: [] }
              : path.includes("/agents/image-agent")
                ? agent
                : [],
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantAgentDraft agentId={agent.id} compact />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

it("keeps the actual agent image and Library link in compact and expanded conversation cards without rerunning", async () => {
  const fetch = mountMedia();
  expect(
    (await screen.findByAltText("Generated image")).getAttribute("src"),
  ).toBe("/api/artifacts/garden/file");
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/garden");
  expect(
    screen.getByText(/Saved media settings · no text model needed/),
  ).toBeTruthy();
  expect(screen.queryByText(/Choose a local model/)).toBeNull();
  expect(screen.queryByText(/In Work/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edit in conversation" }));
  expect(
    (await screen.findByAltText("Generated image")).getAttribute("src"),
  ).toBe("/api/artifacts/garden/file");
  fireEvent.click(screen.getByRole("button", { name: "Back to summary" }));
  expect(await screen.findByAltText("Generated image")).toBeTruthy();
  expect(
    fetch.mock.calls.every(
      ([, options]) => !options?.method || options.method === "GET",
    ),
  ).toBe(true);
});

it("shows the latest pending execution instead of an older successful image", async () => {
  const fetch = mountMedia(true);
  expect(
    await screen.findByRole("heading", {
      name: "Preparing your agent’s output",
    }),
  ).toBeTruthy();
  expect(screen.queryByAltText("Generated image")).toBeNull();
  expect(
    fetch.mock.calls.some(([path]) => path.includes("/artifacts?run_id=photo")),
  ).toBe(false);
});
