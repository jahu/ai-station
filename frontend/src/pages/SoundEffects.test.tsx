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
function mount(entry = "/audio?mode=effects") {
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
it("chooses an owned film and keeps sound description, prompt preparation and effects authority together", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/audio/effects/runs" && init?.method === "POST")
        writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("/capabilities")
            ? { available: true, readiness: "ready" }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.includes("generation/preferences")
                ? { enabled: false }
                : path === "/api/artifacts"
                  ? [
                      {
                        id: "film",
                        type: "video",
                        mime_type: "video/mp4",
                        title: "Forest",
                        original_filename: "forest.mp4",
                        metadata: { frames: 192, fps: 24 },
                      },
                    ]
                  : path.includes("/runs")
                    ? {
                        id: "sound",
                        status: "queued",
                        parameters: {},
                        metadata: {},
                        capability: "audio.effects",
                      }
                    : {
                        id: "film",
                        type: "video",
                        original_filename: "forest.mp4",
                      },
      };
    }),
  );
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Choose from Library" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Choose Forest film" }),
  );
  expect(screen.getByLabelText("Source film preview")).toBeTruthy();
  fireEvent.change(screen.getByLabelText(/What should we hear/), {
    target: { value: "Gentle wind and birds" },
  });
  fireEvent.click(screen.getByText(/Change sounds over time/));
  fireEvent.click(screen.getByRole("button", { name: "Add scene direction" }));
  fireEvent.change(screen.getByLabelText("Scene 1 end in seconds"), {
    target: { value: "2.5" },
  });
  fireEvent.change(screen.getByLabelText("Scene 1 sound description"), {
    target: { value: "A bicycle bell" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Improve my prompt locally/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate sound" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    video_artifact_id: "film",
    cues: [{ start_frame: 0, end_frame: 60, prompt: "A bicycle bell" }],
    prompt: "Gentle wind and birds",
    negative_prompt: "speech, music",
    steps: 25,
    cfg: 4.5,
    gpu: "auto",
    translation: { enhance: true },
  });
  expect(screen.queryByLabelText("Upload speech")).toBeNull();
  expect(screen.queryByRole("link", { name: /Use as speech/ })).toBeNull();
});
it("shows setup state and never advertises an unavailable engine as ready", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () => ({
      available: false,
      readiness: "unavailable",
      reason: path.endsWith("/capabilities") ? "Install local sound model" : "",
      gpus: [],
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(await screen.findByText("Install local sound model")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Generate sound" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/runs")),
  ).toBe(true);
});
