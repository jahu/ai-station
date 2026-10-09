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
  expect(
    await screen.findByRole("dialog", { name: "Choose a model" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("Search models")).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: /27B/ }));
  fireEvent.click(screen.getByText("GPU, context and advanced options"));
  await screen.findByLabelText("GPU 7 · GPU B");
  fireEvent.click(await screen.findByRole("button", { name: "Use model" }));
  await waitFor(() => expect(select).toHaveBeenCalledWith("llamacpp:file"));
  const load = fetch.mock.calls.find((call) => call[0] === "/api/llama/load");
  expect(load).toBeTruthy();
  const body = JSON.parse((load?.[1] as RequestInit).body as string);
  expect(body).toEqual({
    model_file_id: "file",
    gpus: [2, 7],
    context_size: 4096,
  });
  expect(body.cache_type).toBeUndefined();
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

it("coding picker sends q8_0 and a 128k ceiling without promising that size", async () => {
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
    else if (options?.method === "POST") data = { id: "load-run" };
    else
      data = {
        models: [
          {
            id: "file",
            model_key: "llamacpp:file",
            name: "27B.gguf",
            size_bytes: 16000000000,
          },
        ],
        instances: [],
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
          coding
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
  expect(
    screen.getByText(/largest Q8 context that fits the selected GPUs/),
  ).toBeTruthy();
  expect(screen.getByText("Context ceiling")).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "Use model" }));
  await waitFor(() => expect(select).toHaveBeenCalledWith("llamacpp:file"));
  expect(fetch).toHaveBeenCalledWith(
    "/api/llama/load",
    expect.objectContaining({
      body: JSON.stringify({
        model_file_id: "file",
        gpus: [2, 7],
        context_size: 131072,
        cache_type: "q8_0",
      }),
    }),
  );
});

it("checks owned runtime health without signalling an external process", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (String(path).endsWith("/health") && options?.method === "POST") {
        return { id: "health-run" };
      }
      return {
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
            id: "owned",
            status: "ready",
            name: "27B",
            metadata: {
              model_file_id: "file",
              gpus: [2, 7],
              load_run_id: "load",
              health: { status: "ready", alive: true, n_ctx: 4096 },
              health_run_id: "health-run",
            },
          },
        ],
      };
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
          value="llamacpp:file"
          models={[]}
          onSelect={() => undefined}
          busy={false}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Model" }));
  fireEvent.click(await screen.findByRole("button", { name: /27B/ }));
  fireEvent.click(screen.getByText("GPU, context and advanced options"));
  await screen.findByText(/Last health: ready/);
  fireEvent.click(screen.getByRole("button", { name: "Check health" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/llama/owned/health" &&
          call[1]?.method === "POST" &&
          call[1]?.body === "{}",
      ),
    ).toBe(true),
  );
});
