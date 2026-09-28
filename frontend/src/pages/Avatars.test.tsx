import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Avatars from "./Avatars";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("queues portrait and speech with selected video settings", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : path.endsWith("/runs")
          ? { id: "avatar" }
          : [
              { id: "portrait", type: "image", original_filename: "Portrait" },
              { id: "speech", type: "audio", original_filename: "Speech" },
            ],
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
          <Route path="/" element={<Avatars />} />
          <Route path="/runs/:id" element={<h1>Run inspector</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "Portrait" }, { timeout: 5000 });
  fireEvent.change(screen.getByLabelText("Portrait from Library"), {
    target: { value: "portrait" },
  });
  fireEvent.change(screen.getByLabelText("Speech from Library"), {
    target: { value: "speech" },
  });
  fireEvent.change(screen.getByLabelText("Resolution"), {
    target: { value: "256" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Generate avatar video" }),
  );
  await screen.findByRole("heading", { name: "Run inspector" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/avatars/runs",
    expect.objectContaining({
      body: JSON.stringify({
        image_artifact_id: "portrait",
        audio_artifact_id: "speech",
        prompt: "A person speaking naturally, static camera.",
        size: 256,
        frames: 81,
        steps: 8,
        seed: 43,
        gpu: "auto",
      }),
    }),
  );
});
