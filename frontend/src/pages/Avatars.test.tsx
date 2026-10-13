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

it("queues typed speech with a voice reference while keeping recording mode unchanged", async () => {
  const artifacts = [
    {
      id: "portrait",
      type: "image",
      mime_type: "image/png",
      original_filename: "Portrait.png",
    },
    {
      id: "voice",
      type: "audio",
      mime_type: "audio/wav",
      original_filename: "Voice.wav",
    },
  ];
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (path.includes("/runs")) return { id: "speech", status: "queued" };
      if (path.endsWith("/artifacts")) return artifacts;
      return artifacts.find((a) => path.endsWith(a.id));
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?image=portrait&audio=voice");
  expect(screen.queryByLabelText("Words to say")).toBeNull();
  fireEvent.click(screen.getByLabelText("Type what to say"));
  expect(screen.getByText("Voice reference")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Generate avatar video" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Words to say"), {
    target: { value: "Cześć!" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Generate avatar video" }),
  );
  await screen.findByText("Waiting for an available GPU");
  expect(fetch).toHaveBeenCalledWith(
    "/api/avatars/runs",
    expect.objectContaining({
      body: expect.stringContaining('"speech_text":"Cześć!"'),
    }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/avatars/runs",
    expect.objectContaining({
      body: expect.stringContaining('"audio_artifact_id":"voice"'),
    }),
  );
});

it("restores a speech-to-avatar workflow and stops its active animation", async () => {
  const first = {
    id: "speech",
    capability: "audio.speech",
    status: "succeeded",
    parameters: { avatar_after_speech: {} },
  };
  const child = {
    id: "animate",
    capability: "avatar.animate",
    status: "queued",
    parameters: {},
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/workflow")) return { steps: [first, child] };
      if (path.includes("/artifacts?")) return [];
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (options?.method === "POST") return child;
      return first;
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?run=speech");
  await screen.findByRole("list", { name: "Avatar workflow" });
  expect(
    screen.getByRole("link", { name: "1. Speech" }).getAttribute("href"),
  ).toBe("/runs/speech");
  expect(
    screen
      .getByRole("link", { name: "2. Animate portrait" })
      .getAttribute("href"),
  ).toBe("/runs/animate");
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await vi.waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/animate/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    fetch.mock.calls.some(([url]) => url === "/api/runs/speech/cancel"),
  ).toBe(false);
});
