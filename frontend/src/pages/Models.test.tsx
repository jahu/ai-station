import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Models } from "./Models";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
