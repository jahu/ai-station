import { useState } from "react";
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
import StudioShotMedia from "./StudioShotMedia";
import type { StudioRevision } from "./studio-material";
import { initialDefinition } from "../components/creative/creative-project";

const revision: StudioRevision = {
  id: "revision-one",
  material_id: "material-one",
  position: 1,
  parent_revision_id: null,
  source_run_id: null,
  sources: {},
  project_snapshot: {},
  options: initialDefinition().defaults,
  brief: "A cinematic abstract story",
  created_at: "2026-11-11T10:00:00Z",
  storyboard: {
    title: "Light",
    concept: "A reveal",
    hook: "Look closer",
    audio: "silent",
    voice_direction: "",
    music_brief: "",
    scenes: [
      {
        purpose: "An opening reveal",
        duration_frames: 90,
        visual_kind: "image",
        visual_brief: "A prism",
        framing: "Macro",
        source_artifact_id: null,
        reference_artifact_ids: [],
        title: "",
        eyebrow: "",
        body: "",
        points: [],
        narration: "",
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
function setup({
  video = false,
  completed = false,
  active = false,
  disabled = false,
  lost = false,
} = {}) {
  const board = structuredClone(revision);
  board.storyboard.scenes[0].visual_kind = video ? "video" : "image";
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  const run = {
    id: "run-one",
    task_id: "task-one",
    status: active ? "running" : "succeeded",
    parameters: { studio_scene: 0 },
    created_at: "2026-11-11T10:00:00Z",
    executor_type: video ? "media_compose" : "photo_pipe",
  };
  let lose = lost;
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
        if (lose) {
          lose = false;
          throw new Error("Lost response");
        }
        return json({ ...run, status: "queued" }, 202);
      }
      if (path.includes("/production"))
        return json({
          runs: completed || active ? [run] : [],
          artifacts: completed
            ? [
                {
                  id: "film-one",
                  run_id: run.id,
                  type: video ? "video" : "image",
                  created_at: run.created_at,
                },
              ]
            : [],
        });
      if (path.includes("/images/models"))
        return json({
          items: [
            {
              id: "qwen",
              name: "Qwen Image",
              modes: ["t2i", "recompose"],
              available: true,
            },
          ],
        });
      if (path.includes("/video/models")) return json({ items: [] });
      return json({});
    }),
  );
  function ControlledShot() {
    const [picked, setPicked] = useState("");
    return (
      <StudioShotMedia
        materialId="material-one"
        revision={board}
        scene={0}
        disabled={disabled}
        selectedArtifactId={picked}
        onSelect={setPicked}
      />
    );
  }
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
        <ControlledShot />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return requests;
}

it("queues the saved shot with a selected model and retains the receipt after a lost reply", async () => {
  const requests = setup({ lost: true });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Generate image",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Model" }));
  await screen.findByRole("option", { name: "Qwen Image" });
  fireEvent.change(screen.getByLabelText("Shot 1 image model"), {
    target: { value: "qwen" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate image" }));
  await screen.findByText("Lost response");
  fireEvent.click(screen.getByRole("button", { name: "Generate image" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0].body).toEqual(requests[1].body);
  expect(requests[0].body).toMatchObject({
    revision_id: revision.id,
    scene: 0,
    image_model: "qwen",
  });
});
it("shows actual generated footage with playback controls and a Library link", async () => {
  setup({ video: true, completed: true });
  const video = await screen.findByLabelText("Shot 1 generated footage");
  expect(video.getAttribute("src")).toBe("/api/artifacts/film-one/file");
  expect(video.hasAttribute("controls")).toBe(true);
  expect(video.hasAttribute("autoplay")).toBe(false);
  expect(
    screen.getByRole("link", { name: /Open in Library/ }).getAttribute("href"),
  ).toBe("/library/film-one");
  expect(
    (
      screen.getByRole("button", {
        name: "Generate another take",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});
it("stops the complete shot Task while blocking duplicate generation", async () => {
  const requests = setup({ video: true, active: true });
  await screen.findByRole("button", { name: "Stop shot" });
  expect(
    (
      screen.getByRole("button", {
        name: "Generate footage",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Stop shot" }));
  await waitFor(() =>
    expect(requests[0].path).toContain("/shots/run-one/stop"),
  );
});
it("requires saved edits before launching a generation", async () => {
  setup({ disabled: true });
  expect(
    (
      (await screen.findByRole("button", {
        name: "Generate image",
      })) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
