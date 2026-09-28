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
import LlamaModels from "./LlamaModels";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("selects a queued GGUF immediately so the conversation can wait for its load", async () => {
  let started = false;
  const select = vi.fn();
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    let data: unknown;
    if (path.endsWith("/hardware"))
      data = {
        gpus: [
          { index: 2, name: "GPU A" },
          { index: 7, name: "GPU B" },
        ],
      };
    else if (options?.method === "POST") {
      started = true;
      data = { id: "load-run" };
    } else
      data = {
        models: [
          {
            id: "file",
            model_key: "llamacpp:file",
            name: "27B.gguf",
            size_bytes: 16000000000,
          },
        ],
        instances: started
          ? [
              {
                id: "instance",
                status: "queued",
                name: "27B",
                metadata: {
                  model_file_id: "file",
                  gpus: [2, 7],
                  load_run_id: "load-run",
                },
              },
            ]
          : [],
      };
    return { ok: true, json: async () => data };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <LlamaModels onSelect={select} busy={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Local model files · llama.cpp"));
  await screen.findByLabelText("GPU 7 · GPU B");
  fireEvent.click(
    await screen.findByRole("button", { name: "Load and select" }),
  );
  await waitFor(() => expect(select).toHaveBeenCalledWith("llamacpp:file"));
  expect(fetch).toHaveBeenCalledWith(
    "/api/llama/load",
    expect.objectContaining({
      body: JSON.stringify({
        model_file_id: "file",
        gpus: [2, 7],
        context_size: 4096,
      }),
    }),
  );
  expect(
    await screen.findByRole("link", { name: "Inspect runtime Run / cancel" }),
  ).toBeTruthy();
});

it("selects an unloaded model without issuing a load until a message needs it", async () => {
  const select = vi.fn();
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : {
            models: [
              {
                id: "file",
                model_key: "llamacpp:file",
                name: "27B.gguf",
                size_bytes: 16000000000,
              },
            ],
            instances: [
              {
                id: "old",
                status: "stopped",
                name: "27B",
                metadata: {
                  model_file_id: "file",
                  gpus: [2, 7],
                  load_run_id: "load",
                },
              },
            ],
          },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <LlamaModels onSelect={select} busy={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Local model files · llama.cpp"));
  fireEvent.click(
    await screen.findByRole("button", { name: "Use · load when needed" }),
  );
  expect(select).toHaveBeenCalledWith("llamacpp:file");
  expect(fetch.mock.calls.every((call) => !call[0].endsWith("/load"))).toBe(
    true,
  );
});
