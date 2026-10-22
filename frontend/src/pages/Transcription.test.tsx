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
function mount(path = "/audio?mode=transcribe&input=voice") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/audio" element={<Audio />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const completed = {
  id: "asr",
  status: "succeeded",
  metadata: {
    transcription: {
      language: "pl",
      duration_seconds: 14,
      text: "To jest nagranie.",
      segments: [{ start: 0, end: 2, text: "To jest nagranie." }],
      artifacts: { txt: "txt-id", srt: "srt-id", json: "json-id" },
    },
  },
};
it("queues a CPU transcription, retains progress and stops the owned run", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/capabilities")
        ? { available: true }
        : path.includes("/runs")
          ? { id: "asr", status: "running" }
          : {
              id: "voice",
              type: "audio",
              mime_type: "audio/wav",
              original_filename: "record.wav",
            },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Transcribe recording",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Spoken language"), {
    target: { value: "pl" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Transcribe recording" }));
  await screen.findByRole("button", { name: "Stop transcription" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/audio/transcription/runs",
    expect.objectContaining({
      body: JSON.stringify({ audio_artifact_id: "voice", language: "pl" }),
    }),
  );
  const stop = screen.getByRole("button", { name: "Stop transcription" });
  await waitFor(() => expect(stop.hasAttribute("disabled")).toBe(false));
  fireEvent.click(stop);
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/asr/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    (screen.getByRole("button", { name: "Create speech" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
it("restores the transcript from a run URL and offers stored text/subtitles", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/capabilities") ? { available: true } : completed,
    })),
  );
  mount("/audio?mode=transcribe&run=asr");
  await screen.findByText("To jest nagranie.");
  expect(
    screen.getByRole("link", { name: "Subtitles" }).getAttribute("href"),
  ).toBe("/api/artifacts/srt-id/file");
  expect(
    screen.getByRole("link", { name: "Inspect run" }).getAttribute("href"),
  ).toBe("/runs/asr");
  expect(screen.getByText("PL · 0:14")).toBeTruthy();
});
it("shows unavailable setup and does not enqueue an unusable adapter", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: !path.endsWith("/transcription/runs"),
    json: async () => ({
      available: false,
      reason: "Offline model needs setup",
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByText("Offline model needs setup");
  expect(
    (
      screen.getByRole("button", {
        name: "Transcribe recording",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    fetch.mock.calls.every(
      (call) => !String(call[0]).endsWith("/transcription/runs"),
    ),
  ).toBe(true);
});
