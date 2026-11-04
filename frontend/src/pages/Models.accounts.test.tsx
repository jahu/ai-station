import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AccountContext } from "../account-context";
import { ModelDetail, Models } from "./Models";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function workspace(admin: boolean, status = "stopped") {
  const file = {
    id: "file",
    filename: "Shared.gguf",
    host_path: "/models/Shared.gguf",
    root_label: "/models",
    category: "llm",
    format: "gguf",
    family: "Synthetic",
    quantization: "Q4",
    size_bytes: 1024,
    capabilities: ["chat"],
    availability: "present",
    last_scan_run_id: null,
    discovered_at: "2026-10-30T00:00:00Z",
    last_seen_at: "2026-10-30T00:00:00Z",
  };
  const definition = {
    id: "definition",
    name: "Shared preset",
    file_id: "file",
    family: "Synthetic",
    category: "llm",
    status: "registered",
    capabilities: ["chat"],
    last_verify_run_id: null,
    preset: { gpus: [2, 7], context_size: 65536, cache_type: "q8_0" },
    compatibility: {
      operational: true,
      summary: "Managed model",
      runtime: "llama.cpp",
    },
    file,
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (options?.method === "POST")
        return { id: path.endsWith("/load") ? "model-load" : "model-scan" };
      if (path.endsWith("/hardware"))
        return {
          gpus: [
            { index: 2, name: "Device A" },
            { index: 7, name: "Device B" },
          ],
        };
      if (path === "/api/llama")
        return {
          instances: [
            {
              id: "shared",
              status,
              metadata: { model_file_id: "file" },
            },
          ],
        };
      if (path === "/api/models/file")
        return { ...file, definitions: [definition] };
      if (path === "/api/models/definitions")
        return { items: [definition], total: 1 };
      if (path === "/api/models/compatibility")
        return { items: [], note: "Synthetic fixture" };
      return { items: [file], total: 1, latest_scan: null };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AccountContext.Provider
        value={{
          mode: "accounts",
          user: {
            id: "member",
            username: "Member",
            display_name: "Member",
            is_admin: admin,
            enabled: true,
            mfa_enabled: false,
            created_at: "2026-10-30T00:00:00Z",
          },
        }}
      >
        <MemoryRouter initialEntries={["/models"]}>
          <Routes>
            <Route path="/models" element={<Models />} />
            <Route path="/models/:id" element={<ModelDetail />} />
            <Route path="/runs/:id" element={<h1>Owned model operation</h1>} />
          </Routes>
        </MemoryRouter>
      </AccountContext.Provider>
    </QueryClientProvider>,
  );
  return fetch;
}

it("lets a member inspect and load a shared preset without advertising administrator edits", async () => {
  const fetch = workspace(false);
  fireEvent.click(
    await screen.findByRole("link", { name: /Inspect Shared.gguf/ }),
  );
  await screen.findByRole("heading", { name: "Shared.gguf" });
  expect(screen.getByText("Shared preset")).toBeTruthy();
  expect(screen.getByText(`${(65536).toLocaleString()} tokens`)).toBeTruthy();
  expect(screen.queryByLabelText("Display name")).toBeNull();
  for (const name of [
    "Save preset",
    "Re-check installation",
    "Remove definition",
    "Restart owned runtime",
  ]) {
    expect(screen.queryByRole("button", { name })).toBeNull();
  }
  expect(
    screen.queryByRole("link", { name: "Inspect runtime diagnostics" }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: "Check health" })).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Load with saved preset" }),
  );
  await screen.findByRole("heading", { name: "Owned model operation" });
  const mutations = fetch.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(mutations).toHaveLength(1);
  expect(mutations[0][0]).toBe("/api/models/definitions/definition/load");
});

it("restricts discovery to the administrator while keeping model files visible to members", async () => {
  workspace(false);
  await screen.findByRole("link", { name: /Inspect Shared.gguf/ });
  expect(screen.queryByRole("button", { name: "Discover models" })).toBeNull();
  cleanup();
  const fetch = workspace(true);
  fireEvent.click(
    await screen.findByRole("button", { name: "Discover models" }),
  );
  await screen.findByRole("heading", { name: "Owned model operation" });
  expect(
    fetch.mock.calls.some(
      ([path, options]) =>
        path === "/api/models/discover" && options?.method === "POST",
    ),
  ).toBe(true);
});

it("does not offer a redundant load while a shared model is already ready", async () => {
  const fetch = workspace(false, "ready");
  fireEvent.click(
    await screen.findByRole("link", { name: /Inspect Shared.gguf/ }),
  );
  await screen.findByRole("heading", { name: "Shared.gguf" });
  const load = screen.getByRole("button", {
    name: "Load with saved preset",
  }) as HTMLButtonElement;
  expect(load.disabled).toBe(true);
  fireEvent.click(load);
  expect(
    fetch.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});
