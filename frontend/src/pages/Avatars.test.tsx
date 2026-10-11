import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Avatars from "./Avatars";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/avatars") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/avatars" element={<Avatars />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
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
  mount();
  fireEvent.click(
    screen.getAllByRole("button", { name: "Choose from Library" })[0],
  );
  fireEvent.click(
    await within(
      screen.getByRole("region", { name: "Portrait library" }),
    ).findByRole(
      "button",
      { name: "Choose Portrait.png portrait" },
      { timeout: 5000 },
    ),
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Choose from Library" })[1],
  );
  fireEvent.click(
    await within(
      screen.getByRole("region", { name: "Speech recording library" }),
    ).findByRole("button", { name: "Choose Speech.wav speech" }),
  );
  const qualityList = screen
    .getByLabelText("Quality 384")
    .closest(".avatar-quality-choice-list") as HTMLElement;
  fireEvent.keyDown(qualityList, { key: "Home" });
  fireEvent.keyDown(qualityList, { key: "Enter" });
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
        path.endsWith("/lineage")
          ? { id: "movie", sources: [], derived: [] }
          : path.includes("/artifacts?")
            ? [{ id: "movie", type: "video" }]
            : path.includes("/runs/")
              ? { id: "done", status: "succeeded" }
              : { gpus: [] },
    })),
  );
  mount("/avatars?run=done");
  const video = await screen.findByLabelText("Generated video");
  expect(video.getAttribute("src")).toBe("/api/artifacts/movie/file");
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/movie");
});
it("stages a portrait and speech from the URL without queueing a Run", async () => {
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
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      const url = String(path);
      if (url.endsWith("/hardware")) return { gpus: [] };
      return artifacts.find((artifact) => url.endsWith(artifact.id)) ?? {};
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?image=portrait&audio=speech");
  await screen.findByText("Portrait.png");
  await screen.findByText("Speech.wav");
  expect(
    screen
      .getByRole("button", { name: "Generate avatar video" })
      .hasAttribute("disabled"),
  ).toBe(false);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});
