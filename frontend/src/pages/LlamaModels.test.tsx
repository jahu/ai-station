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

it("loads a stored GGUF across discovered GPUs and selects it after readiness", async () => {
  let ready = false;
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
      ready = true;
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
        instances: ready
          ? [
              {
                id: "instance",
                status: "ready",
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
  expect(screen.getByRole("button", { name: "Stop model" })).toBeTruthy();
});
