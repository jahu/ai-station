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
        <LlamaModels
          value="qwen"
          models={["qwen"]}
          onSelect={select}
          busy={false}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Model" }));
  fireEvent.click(await screen.findByRole("button", { name: /27B/ }));
  fireEvent.click(screen.getByText("GPU, context and advanced options"));
  await screen.findByLabelText("GPU 7 · GPU B");
  fireEvent.click(await screen.findByRole("button", { name: "Use model" }));
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
    await screen.findByRole("link", { name: "Model operation →" }),
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
        <LlamaModels
          value="qwen"
          models={["qwen"]}
          onSelect={select}
          busy={false}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Model" }));
  fireEvent.click(await screen.findByRole("button", { name: /27B/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Use model" }));
  expect(select).toHaveBeenCalledWith("llamacpp:file");
  expect(fetch.mock.calls.every((call) => !call[0].endsWith("/load"))).toBe(
    true,
  );
});

it("keeps the previous selection when a first load is rejected", async () => {
  const select = vi.fn();
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options?.method !== "POST",
    status: options?.method === "POST" ? 409 : 200,
    json: async () =>
      options?.method === "POST"
        ? { detail: "GPU busy; try again" }
        : path.endsWith("/hardware")
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
              instances: [],
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
        <LlamaModels
          value="qwen"
          models={["qwen"]}
          onSelect={select}
          busy={false}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Model" }));
  fireEvent.click(await screen.findByRole("button", { name: /27B/ }));
  fireEvent.click(screen.getByRole("button", { name: "Use model" }));
  await screen.findByText("GPU busy; try again");
  expect(select).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "qwen, local server" }));
  fireEvent.click(screen.getByRole("button", { name: "Use model" }));
  expect(select).toHaveBeenCalledWith("qwen");
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(1);
});
