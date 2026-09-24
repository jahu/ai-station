import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Images from "./Images";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/images") {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/images" element={<Images />} />
          <Route path="/runs/:id" element={<h1>Run inspector</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("queues Juggernaut parameters and opens the durable run", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [{ index: 7, name: "GPU" }] }
        : { id: "run-id" },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.change(screen.getByLabelText("Backend"), {
    target: { value: "juggernaut" },
  });
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A forest" },
  });
  fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "123" } });
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await screen.findByRole("heading", { name: "Run inspector" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({ body: expect.stringContaining('"seed":123') }),
  );
});
it("reuses a Library source, shows upscale dimensions, and submits its identity", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.includes("/artifacts/")
        ? { id: "source", metadata: { width: 200, height: 100 } }
        : path.endsWith("/hardware")
          ? { gpus: [] }
          : { id: "next" },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/images?mode=upscale&input=source");
  await screen.findByText(/Expected output: 800 × 400/);
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Queue upscale" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Queue upscale" }));
  await screen.findByRole("heading", { name: "Run inspector" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({
      body: expect.stringContaining('"input_artifact_ids":["source"]'),
    }),
  );
});
