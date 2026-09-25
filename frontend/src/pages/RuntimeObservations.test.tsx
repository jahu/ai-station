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
