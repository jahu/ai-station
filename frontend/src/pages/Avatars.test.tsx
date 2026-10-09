import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Avatars from "./Avatars";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("selects existing inputs, queues video and keeps the live result beside the form", async () => {
  const artifacts = [
    {
      id: "portrait",
      type: "image",
      mime_type: "image/png",
      original_filename: "Portrait.png",
    },
    {
      id: "speech",
      type: "audio",
      mime_type: "audio/wav",
      original_filename: "Speech.wav",
    },
  ];
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : path.includes("/runs")
          ? { id: "avatar", status: "queued" }
          : path.endsWith("/artifacts")
            ? artifacts
            : artifacts.find((a) => path.endsWith(a.id)),
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Avatars />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Choose from Library" })[0],
  );
  fireEvent.click(
    await within(
      screen.getByRole("region", { name: "Portrait library" }),
    ).findByRole("button", { name: "Choose Portrait.png portrait" }, { timeout: 5000 }),
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Choose from Library" })[1],
  );
  fireEvent.click(
    await within(
      screen.getByRole("region", { name: "Speech recording library" }),
    ).findByRole("button", { name: "Choose Speech.wav speech" }),
  );
  fireEvent.change(screen.getByLabelText("Resolution"), {
    target: { value: "256" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Generate avatar video" }),
  );
  await screen.findByText("Waiting for an available GPU");
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
it("restores a completed video from the workspace URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.includes("/artifacts?")
          ? [{ id: "movie", type: "video" }]
          : path.includes("/runs/")
            ? { id: "done", status: "succeeded" }
            : { gpus: [] },
    })),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/avatars?run=done"]}>
        <Avatars />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const video = await screen.findByLabelText("Generated video");
  expect(video.getAttribute("src")).toBe("/api/artifacts/movie/file");
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/movie");
});
