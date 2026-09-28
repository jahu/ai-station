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
import Audio from "./Audio";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
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
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Audio />
      </MemoryRouter>
    </QueryClientProvider>,
  );
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
