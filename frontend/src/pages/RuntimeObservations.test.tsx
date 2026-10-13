import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RuntimeObservations from "./RuntimeObservations";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("labels external observations and enqueues refresh only on request", async () => {
  const fetch = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options
        ? { id: "observation" }
        : {
            items: [
              {
                id: "process",
                name: "Ollama",
                status: "observed",
                ownership: "external",
                endpoint: "",
                updated_at: "2026-09-25T12:00:00Z",
                stale: true,
                metadata: { source: "host_process", pid: 42 },
              },
            ],
            total: 1,
            latest_scan: null,
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
          <Route path="/" element={<RuntimeObservations />} />
          <Route path="/runs/:id" element={<h1>Observation Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Ollama");
  expect(screen.getByText("external")).toBeTruthy();
  expect(screen.getByText(/Process observation does not verify/)).toBeTruthy();
  expect(fetch.mock.calls.filter((call) => call[1])).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Observe runtimes" }));
  await screen.findByRole("heading", { name: "Observation Run" });
  expect(fetch.mock.calls.filter((call) => call[1])[0][0]).toBe(
    "/api/runtimes/observe",
  );
});

it("moves through runtime observations with arrow keys", async () => {
  const row = {
    status: "observed",
    ownership: "external",
    endpoint: "",
    updated_at: "2026-10-09T12:00:00Z",
    stale: false,
    metadata: { source: "host_process", pid: 42, scan_run_id: "scan" },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        items: [
          { ...row, id: "rt-one1", name: "Ollama" },
          {
            ...row,
            id: "rt-two2",
            name: "llama-server",
            metadata: { ...row.metadata, pid: 99, scan_run_id: "scan-two" },
          },
        ],
        total: 2,
        latest_scan: null,
      }),
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <RuntimeObservations />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect Ollama rt-one1",
  });
  const second = screen.getByRole("link", {
    name: "Inspect llama-server rt-two2",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Runtime observations" }),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", { name: "Inspect llama-server rt-two2" })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
