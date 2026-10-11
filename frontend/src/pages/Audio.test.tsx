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
import Audio from "./Audio";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/audio") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/audio" element={<Audio />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("keeps speech generation in the workspace with visible progress and stop", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : path.includes("/runs")
          ? { id: "speech", status: "queued" }
          : {
              id: "voice",
              original_filename: "reference.wav",
              type: "audio",
              mime_type: "audio/wav",
            },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    screen
      .getByRole("button", { name: "Generate speech" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Upload speech"), {
    target: {
      files: [new File(["wav"], "reference.wav", { type: "audio/wav" })],
    },
  });
  await screen.findByText("reference.wav");
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Witaj" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await screen.findByText("Waiting for an available GPU");
  expect(
    screen
      .getByRole("button", { name: "Generating speech…" })
      .hasAttribute("disabled"),
  ).toBe(true);
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/audio/runs",
      expect.objectContaining({
        body: JSON.stringify({
          text: "Witaj",
          gpu: "auto",
          reference_artifact_id: "voice",
        }),
      }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/speech/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});
it("reuses the finished speech as the next voice without queueing a Run", async () => {
  const spoken = {
    id: "spoken01",
    type: "audio",
    mime_type: "audio/wav",
    original_filename: "line.wav",
    title: "Spoken line",
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      const url = String(path);
      if (url.endsWith("/hardware")) return { gpus: [] };
      if (url.endsWith("/lineage"))
        return { id: "spoken01", sources: [], derived: [] };
      if (url.includes("/artifacts?")) return [spoken];
      if (url.includes("/artifacts/")) return spoken;
      if (url.includes("/runs/")) return { id: "done", status: "succeeded" };
      return {};
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/audio?run=done");
  fireEvent.click(
    await screen.findByRole("link", {
      name: "Use as voice reference spoken01",
    }),
  );
  await screen.findByText("Spoken line");
  expect(screen.getByLabelText("Generated audio")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Generate speech" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
