import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import VoiceVolumeAction from "./VoiceVolumeAction";
import type { Artifact } from "../../api";

const source = {
  id: "audio-source",
  type: "audio",
  mime_type: "audio/wav",
  metadata: {},
  original_filename: "voice.wav",
} as Artifact;
function show(a = source) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <VoiceVolumeAction artifact={a} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());
it("queues a separate repair and links to the copy while retaining the original", async () => {
  const fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.endsWith("/voice-level"))
      return new Response(
        JSON.stringify({ id: "volume-run", status: "queued" }),
      );
    if (url.endsWith("/runs/volume-run"))
      return new Response(
        JSON.stringify({
          id: "volume-run",
          status: "succeeded",
          metadata: { result_artifact_id: "balanced-copy" },
        }),
      );
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  show();
  expect(screen.getByText(/The original is kept/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Even out voice volume" }),
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole("link", { name: "Open balanced copy" })
        .getAttribute("href"),
    ).toBe("/library/balanced-copy"),
  );
  const call = fetch.mock.calls.find(([url]) =>
    String(url).endsWith("/voice-level"),
  )!;
  expect(call[1].method).toBe("POST");
  expect(JSON.parse(call[1].body).client_request_id).toMatch(/^[a-f0-9-]{36}$/);
});
it("avoids processing balanced audio twice", () => {
  show({
    ...source,
    metadata: { audio_leveling: { profile: "speech-volume-v1" } },
  });
  expect(screen.getByText("Voice volume balanced")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});
it("does not offer processing for trashed media", () => {
  show({ ...source, trashed_at: "2026-11-08T00:00:00Z" });
  expect(screen.queryByRole("button")).toBeNull();
});
