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
import {
  CreativeContext,
  type CreativeTurn,
} from "../components/creative/creative-context";
import TimelineEditor from "./TimelineEditor";
import type { Manifest } from "../components/timeline/timeline";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("assembles media, trims and positions independent audio, saves and queues the exact private edit", async () => {
  const video = "11111111-1111-4111-8111-111111111111",
    audio = "22222222-2222-4222-8222-222222222222";
  const sources = {
    [video]: {
      artifact_id: video,
      kind: "video",
      title: "Studio film",
      frames: 48,
      fps: 24,
      width: 128,
      height: 128,
    },
    [audio]: {
      artifact_id: audio,
      kind: "audio",
      title: "Voiceover",
      samples: 24000,
      sample_rate: 24000,
      channels: 1,
    },
  };
  const saves: { manifest: Manifest; client_request_id: string }[] = [];
  const draft = vi.fn(),
    generate = vi.fn(
      async () =>
        ({
          run: {
            id: "preview",
            status: "queued",
            parameters: {},
            metadata: {},
          },
        }) as CreativeTurn,
    );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      let value: unknown = {};
      if (url === "/api/timelines/capabilities") value = { available: true };
      else if (url.startsWith("/api/timelines/sources/"))
        value = sources[url.split("/").at(-1)! as keyof typeof sources];
      else if (url.startsWith("/api/artifacts?kind="))
        value = url.includes("kind=video")
          ? [
              {
                id: video,
                title: "Studio film",
                type: "video",
                mime_type: "video/mp4",
              },
            ]
          : [
              {
                id: audio,
                title: "Voiceover",
                type: "audio",
                mime_type: "audio/wav",
              },
            ];
      else if (
        url === "/api/timelines/workspace/revisions" &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body));
        saves.push(body);
        value = {
          id: "saved-edit",
          position: 1,
          manifest: body.manifest,
          created_at: "2026-10-30T12:00:00Z",
        };
      } else if (url === "/api/timelines/workspace/revisions") value = [];
      else if (url.includes("/waveforms/"))
        value = {
          id: "wave",
          status: "succeeded",
          parameters: {},
          metadata: { waveform: { peaks: Array(512).fill(0.25) } },
        };
      else if (url.endsWith("/runs/wave"))
        value = {
          id: "wave",
          status: "succeeded",
          parameters: {},
          metadata: { waveform: { peaks: Array(512).fill(0.25) } },
        };
      else if (url.endsWith("/runs/preview"))
        value = {
          id: "preview",
          status: "queued",
          parameters: {},
          metadata: {},
        };
      return { ok: true, json: async () => value };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CreativeContext.Provider
          value={{
            id: "workspace",
            formKey: "workspace:0",
            draft: {},
            setDraft: draft,
            generate,
          }}
        >
          <TimelineEditor />
        </CreativeContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Video" }));
  fireEvent.click(await screen.findByRole("button", { name: "Studio film" }));
  await screen.findByLabelText("Source out (seconds)");
  fireEvent.change(screen.getByLabelText("Source out (seconds)"), {
    target: { value: "1.5" },
  });
  fireEvent.change(screen.getByLabelText("Start on timeline (seconds)"), {
    target: { value: "0.5" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Mute original sound/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Audio" }));
  fireEvent.click(await screen.findByRole("button", { name: "Voiceover" }));
  await screen.findByLabelText("Duration (seconds)");
  fireEvent.change(screen.getByLabelText("Start on timeline (seconds)"), {
    target: { value: "1" },
  });
  fireEvent.change(screen.getByLabelText("Audio fade in (seconds)"), {
    target: { value: "0.25" },
  });
  fireEvent.change(screen.getByLabelText("Audio fade out (seconds)"), {
    target: { value: "0.25" },
  });
  fireEvent.change(screen.getByLabelText("Clip volume"), {
    target: { value: "0.4" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save edit" }));
  await waitFor(() => expect(saves).toHaveLength(1));
  expect(saves[0].manifest.clips[0]).toMatchObject({
    artifact_id: video,
    in_frame: 0,
    out_frame: 36,
    start_frame: 12,
    muted: true,
  });
  expect(saves[0].manifest.tracks[0]).toMatchObject({
    artifact_id: audio,
    start_frame: 24,
    duration_frames: 24,
    fade_in_frames: 6,
    fade_out_frames: 6,
    gain: 0.4,
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview this edit" }));
  await waitFor(() => expect(generate).toHaveBeenCalledOnce());
  expect(generate).toHaveBeenCalledWith({
    revision_id: "saved-edit",
    manifest: saves[0].manifest,
  });
  expect(saves).toHaveLength(1);
  expect(
    draft.mock.calls.at(-1)?.[0].formState.manifest.tracks[0].artifact_id,
  ).toBe(audio);
  expect(
    await screen.findByRole("button", { name: "Stop render" }),
  ).toBeTruthy();
});

it("restores an input-linked workspace without appending the source a second time", async () => {
  const video = "11111111-1111-4111-8111-111111111111";
  const manifest: Manifest = {
    fps: 24,
    width: 128,
    height: 128,
    clips: [
      {
        artifact_id: video,
        in_frame: 0,
        out_frame: 48,
        start_frame: 0,
        gain: 1,
        muted: false,
        fade_in_frames: 0,
        fade_out_frames: 0,
      },
    ],
    tracks: [],
  };
  const draft = vi.fn();
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("/sources/")
        ? {
            artifact_id: video,
            kind: "video",
            title: "Retained film",
            frames: 48,
            fps: 24,
            width: 128,
            height: 128,
          }
        : url.includes("capabilities")
          ? { available: true }
          : [],
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/video?mode=edit&input=" + video]}>
        <CreativeContext.Provider
          value={{
            id: "workspace",
            formKey: "workspace:0",
            draft: { formState: { manifest } },
            generate: vi.fn(),
            setDraft: draft,
          }}
        >
          <TimelineEditor />
        </CreativeContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("button", { name: "Video clip 1: Retained film" });
  await waitFor(() => expect(draft).toHaveBeenCalled());
  expect(draft.mock.calls.at(-1)?.[0].formState.manifest.clips).toHaveLength(1);
  expect(
    fetch.mock.calls.filter(([url]) => url.includes("/sources/")),
  ).toHaveLength(1);
});
