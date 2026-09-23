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
import { Runs } from "./Runs";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the actual API failure instead of an empty successful history", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Database unavailable" }),
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Database unavailable",
  );
});

it("requests the selected status and links persisted runs to their inspector", async () => {
  const fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [
      {
        id: "one",
        capability: "image.generate",
        executor_type: "photo_pipe",
        execution_target: "host",
        status: "running",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    (await screen.findByRole("link", { name: /image.generate/ })).getAttribute(
      "href",
    ),
  ).toBe("/runs/one");
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "running" },
  });
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith("/api/runs?status=running", undefined),
  );
});
