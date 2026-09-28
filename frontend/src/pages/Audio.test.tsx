import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Audio from "./Audio";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("uploads a voice reference and queues an inspectable speech Run", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [{ index: 7, name: "GPU" }] }
        : path.endsWith("/runs")
          ? { id: "speech" }
          : { id: "voice", original_filename: "reference.wav", type: "audio" },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/audio"]}>
        <Routes>
          <Route path="/audio" element={<Audio />} />
          <Route path="/runs/:id" element={<h1>Run inspector</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    screen
      .getByRole("button", { name: "Generate speech" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Voice reference · WAV"), {
    target: {
      files: [new File(["wav"], "reference.wav", { type: "audio/wav" })],
    },
  });
  await screen.findByText("reference.wav");
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Witaj" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await screen.findByRole("heading", { name: "Run inspector" });
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
});
