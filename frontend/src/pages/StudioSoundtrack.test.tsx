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
import StudioSoundtrack from "./StudioSoundtrack";
import type { StudioRevision } from "./studio-material";
import { initialDefinition } from "../components/creative/creative-project";

const revision: StudioRevision = {
  id: "revision-one",
  material_id: "material-one",
  parent_revision_id: null,
  source_run_id: null,
  position: 1,
  options: initialDefinition().defaults,
  sources: {},
  project_snapshot: {},
  brief: "Explain a useful idea",
  created_at: "2026-11-11T10:00:00Z",
  storyboard: {
    title: "A useful idea",
    concept: "A story in two beats",
    hook: "Look closer",
    audio: "voice_music",
    voice_direction: "Warm and clear",
    music_brief: "A restrained instrumental score",
    scenes: [
      {
        purpose: "A reveal",
        duration_frames: 90,
        visual_kind: "image",
        visual_brief: "A glass prism",
        framing: "Macro",
        source_artifact_id: null,
        reference_artifact_ids: [],
        title: "",
        eyebrow: "",
        body: "",
        points: [],
        narration: "Look a little closer.",
        layout: "full_bleed",
        media_motion: "push_in",
        media_fit: "cover",
        media_start_seconds: 0,
      },
    ],
  },
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup({ finished = false, available = true, disabled = false } = {}) {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  const onMeasured = vi.fn(async () => {});
  const root = {
    id: "audio-root",
    task_id: "audio-task",
    status: "succeeded",
    parameters: { studio_audio_root_id: "audio-root" },
  };
  let rows: unknown[] = finished
    ? [
        {
          root_run: root,
          status: "succeeded",
          runs: [],
          active_run_ids: [],
          failed_run: null,
          soundtrack: { id: "soundtrack-one" },
          measured_revision_id: "revision-two",
        },
      ]
    : [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const json = (v: unknown, status = 200) =>
        new Response(JSON.stringify(v), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      if (init?.method === "POST") {
        requests.push({ path, body: JSON.parse(String(init.body)) });
        rows = [
          {
            root_run: root,
            status: "queued",
            runs: [{ ...root, status: "queued" }],
            active_run_ids: [root.id],
            failed_run: null,
            soundtrack: null,
            measured_revision_id: null,
          },
        ];
        return json({ ...root, status: "queued" }, 202);
      }
      if (path.includes("/audio/productions")) return json(rows);
      if (path.endsWith("/audio/capabilities"))
        return json({
          available,
          languages: ["pl", "en"],
          engines: {
            fish_s2_pro: {
              available,
              readiness: "ready",
              voice_sources: ["model", "reference"],
            },
          },
        });
      if (path.endsWith("/audio/music/capabilities"))
        return json({ available });
      if (
        path.endsWith("/audio/models") ||
        path.endsWith("/audio/music/models")
      )
        return json({ items: [] });
      return json({});
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>
        <StudioSoundtrack
          materialId="material-one"
          revision={revision}
          disabled={disabled}
          onMeasured={onMeasured}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { requests, onMeasured };
}
it("starts a whole soundtrack with one narrator and the storyboard's score direction", async () => {
  const { requests } = setup();
  const button = await screen.findByRole("button", {
    name: "Create soundtrack",
  });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop sound" });
  expect(requests[0].body).toMatchObject({
    revision_id: "revision-one",
    voice: { engine: "fish_s2_pro", reference_artifact_id: null },
  });
  expect(requests[0].body).not.toHaveProperty("music_caption");
  expect(screen.queryByRole("textbox", { name: "Score direction" })).toBeNull();
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Stop sound" }));
  await waitFor(() =>
    expect(requests[1].path).toContain("/audio/audio-root/stop"),
  );
});
it("plays the actual completed PCM and lets the user apply measured timing", async () => {
  const { onMeasured } = setup({ finished: true });
  const player = await screen.findByLabelText("Finished soundtrack");
  expect(player.getAttribute("src")).toBe("/api/artifacts/soundtrack-one/file");
  expect(player.hasAttribute("controls")).toBe(true);
  expect(player.hasAttribute("autoplay")).toBe(false);
  fireEvent.click(
    screen.getByRole("button", { name: "Apply measured timing & audio" }),
  );
  await waitFor(() => expect(onMeasured).toHaveBeenCalledWith("revision-two"));
});
it("shows actual missing setup and prevents an unavailable model submission", async () => {
  setup({ available: false });
  await screen.findByText(/Prepare a local speech model/);
  expect(
    (
      screen.getByRole("button", {
        name: "Create soundtrack",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getAllByRole("link", { name: "Open Models" }).length,
  ).toBeGreaterThan(0);
});
it("unsaved scene edits cannot be replaced by a measured version", async () => {
  const { onMeasured } = setup({ finished: true, disabled: true });
  const button = await screen.findByRole("button", {
    name: "Apply measured timing & audio",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(button);
  expect(onMeasured).not.toHaveBeenCalled();
});
