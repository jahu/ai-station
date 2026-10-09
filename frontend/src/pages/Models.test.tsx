import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ModelDetail, Models } from "./Models";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("saves a definition and installs it only after an explicit action", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (String(url).includes("/models/compatibility")) {
        return {
          items: [
            {
              format: "gguf",
              category: "llm",
              runtime: "llama.cpp",
              operational: true,
              summary: "never downloads weights",
            },
          ],
          note: "Declared pairings, not a successful load",
        };
      }
      if (String(url).includes("/models/definitions") && options?.method === "POST") {
        return { id: "def-1", status: "unverified", name: "Qwen" };
      }
      if (String(url).includes("/install")) {
        return { id: "install-run" };
      }
      if (String(url).includes("/models/definitions")) {
        return { items: [], total: 0 };
      }
      return { items: [], total: 0, latest_scan: null };
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
        <Routes>
          <Route path="/" element={<Models />} />
          <Route path="/models/:id" element={<h1>File</h1>} />
          <Route path="/runs/:id" element={<h1>Install Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/Declared pairings, not a successful load/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Definitions" }));
  await screen.findByRole("heading", { name: "No curated definitions yet" });
  expect(
    fetch.mock.calls.some((call) => String(call[0]).includes("/install")),
  ).toBe(false);
});

it("starts discovery only after explicit action and opens its durable Run", async () => {
  const fetch = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options ? { id: "scan" } : { items: [], total: 0, latest_scan: null },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<Models />} />
          <Route path="/runs/:id" element={<h1>Discovery Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "No model files in this view" });
  expect(fetch.mock.calls.filter((call) => call[1])).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Discover models" }));
  await screen.findByRole("heading", { name: "Discovery Run" });
  const call = fetch.mock.calls.find((call) => call[1])!;
  expect(call[0]).toBe("/api/models/discover");
  expect(JSON.parse(call[1]!.body as string)).toEqual({});
});

it("registers a definition from a present file without installing until asked", async () => {
  let definition: {
    id: string;
    name: string;
    status: string;
    last_verify_run_id: string | null;
    preset: { gpus: number[]; context_size: number; cache_type: string };
    compatibility: { operational: boolean; summary: string };
  } | null = null;
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (String(url).includes("/system/hardware")) {
        return { gpus: [{ index: 0, name: "GPU 0" }] };
      }
      if (String(url).includes("/llama")) {
        return { models: [], instances: [] };
      }
      if (String(url).includes("/models/definitions") && options?.method === "POST") {
        definition = {
          id: "def-1",
          name: JSON.parse(String(options.body)).name,
          status: "unverified",
          last_verify_run_id: null,
          preset: {
            gpus: [0],
            context_size: 4096,
            cache_type: "f16",
          },
          compatibility: {
            operational: true,
            summary: "Managed llama.cpp after install",
          },
        };
        return definition;
      }
      if (String(url).includes("/install")) {
        return { id: "install-run" };
      }
      return {
        id: "file-1",
        filename: "Qwen.gguf",
        host_path: "/models/Qwen.gguf",
        root_label: "/models",
        category: "llm",
        format: "gguf",
        size_bytes: 1024,
        family: "qwen",
        quantization: "Q4_K_M",
        capabilities: ["chat"],
        availability: "present",
        discovered_at: "2026-01-01T00:00:00Z",
        last_seen_at: "2026-01-01T00:00:00Z",
        last_scan_run_id: "scan-1",
        definitions: definition ? [definition] : [],
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
      <MemoryRouter initialEntries={["/models/file-1"]}>
        <Routes>
          <Route path="/models/:id" element={<ModelDetail />} />
          <Route path="/runs/:id" element={<h1>Install Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Qwen.gguf" });
  expect(
    fetch.mock.calls.some((call) => String(call[0]).includes("/install")),
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Save definition" }));
  await screen.findByRole("button", { name: "Install locally" });
  fireEvent.click(screen.getByRole("button", { name: "Install locally" }));
  await screen.findByRole("heading", { name: "Install Run" });
  const created = fetch.mock.calls.find((call) =>
    String(call[0]).endsWith("/models/definitions"),
  );
  expect(JSON.parse(created![1]!.body as string)).toMatchObject({
    file_id: "file-1",
    name: "Qwen",
  });
});
