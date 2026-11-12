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
import StudioExport from "./StudioExport";
import { initialDefinition } from "../components/creative/creative-project";
import type { StudioRevision } from "./studio-material";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup({
  available = true,
  disabled = false,
  readOnly = false,
  video = false,
  short = false,
  wrongKind = false,
  sound = false,
  measured = true,
  finished = false,
  selectedTake = "take-old",
  shared = false,
  sharedTrim = 0,
  presenterSeconds = 8,
} = {}) {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  const revision: StudioRevision = {
    id: "revision-one",
    material_id: "material-one",
    parent_revision_id: null,
    source_run_id: null,
    position: 1,
    options: initialDefinition().defaults,
    sources: {},
    project_snapshot: {},
    brief: "A visual story",
    created_at: "2026-11-11T10:00:00Z",
    storyboard: {
      title: "A visual story",
      concept: "Make the idea visible",
      hook: "Look closer",
      audio: sound ? "voice_music" : "silent",
      voice_direction: "",
      music_brief: "Instrumental piano",
      scenes: [
        {
          purpose: "Show the idea",
          duration_frames: 90,
          visual_kind: video ? "video" : "image",
          visual_brief: "A prism in light",
          framing: "Macro",
          source_artifact_id: null,
          reference_artifact_ids: [],
          layout: "full_bleed",
          title: "",
          eyebrow: "",
          body: "",
          points: [],
          narration: sound ? "Look closer." : "",
          media_motion: "push_in",
          media_fit: "cover",
          media_start_seconds: 0,
        },
      ],
    },
  };
  if (shared)
    revision.storyboard.scenes.push({
      ...revision.storyboard.scenes[0],
      visual_kind: "reuse",
      reuse_scene: 0,
      duration_frames: 120,
      media_start_seconds: sharedTrim,
    });
  const root = {
    id: "export-one",
    task_id: "export-task",
    status: finished ? "succeeded" : "queued",
    parameters: {},
  };
  let history = {
    runs: finished ? [root] : [],
    artifacts: finished
      ? [{ id: "film-one", run_id: root.id, original_filename: "story.mp4" }]
      : [],
  };
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
        requests.push({
          path,
          body: init.body ? JSON.parse(String(init.body)) : {},
        });
        if (path.endsWith("/cancel"))
          return json({ status: "cancel_requested" });
        history = { runs: [{ ...root, status: "queued" }], artifacts: [] };
        return json({ ...root, status: "queued" }, 202);
      }
      if (path.includes("/exports?")) return json(history);
      if (path.includes("/artifacts?"))
        return json([
          {
            id: "presenter-one",
            type: "video",
            mime_type: "video/mp4",
            title: "My presenter",
            original_filename: "presenter.mp4",
            metadata: { duration_seconds: presenterSeconds },
          },
        ]);
      if (path.endsWith("/renderer/capabilities"))
        return json({
          available,
          reason: available ? "" : "Renderer not prepared",
        });
      if (path.includes("/audio/productions"))
        return json([
          {
            measured_revision_id: measured ? revision.id : "another-version",
            soundtrack: { id: "full-mix" },
            active_run_ids: [],
          },
        ]);
      if (path.endsWith("/production"))
        return json({
          runs: ["new", "old"].map((id) => ({
            id: "run-" + id,
            status: "succeeded",
            parameters: { studio_scene: 0 },
          })),
          artifacts: ["new", "old"].map((id) => ({
            id: "take-" + id,
            run_id: "run-" + id,
            type: video && !wrongKind ? "video" : "image",
            metadata: { duration_seconds: short ? 1 : 8 },
          })),
        });
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
        <StudioExport
          materialId="material-one"
          revision={revision}
          selectedTakes={{ 0: selectedTake }}
          disabled={disabled}
          readOnly={readOnly}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return requests;
}
it("freezes the selected presenter and position without replacing the soundtrack", async () => {
  const requests = setup({ sound: true });
  fireEvent.click(screen.getByRole("button", { name: "Videos from Library" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /^Choose My presenter/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  expect(screen.getByLabelText("Selected presenter clip")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Presenter position"), {
    target: { value: "right" },
  });
  const button = screen.getByRole("button", { name: "Export film" });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop export" });
  expect(requests[0].body).toMatchObject({
    soundtrack_artifact_id: "full-mix",
    presenter: {
      media: "presenter-one",
      placement: "right",
      media_start_seconds: 0,
    },
  });
  expect(
    (
      screen.getByRole("button", {
        name: "Remove presenter",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("blocks short presenter footage and allows removing it without changing the story", async () => {
  const requests = setup({ presenterSeconds: 1 });
  fireEvent.click(screen.getByRole("button", { name: "Videos from Library" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /^Choose My presenter/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  const button = screen.getByRole("button", { name: "Export film" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/It will not be looped or frozen/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Remove presenter" }));
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop export" });
  expect(requests[0].body).not.toHaveProperty("presenter");
});

it("exports the actual selected take and saved version, then stops through the owned Run", async () => {
  const requests = setup();
  const button = await screen.findByRole("button", { name: "Export film" });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop export" });
  expect(requests[0].body).toMatchObject({
    revision_id: "revision-one",
    bindings: [{ scene: 0, artifact_id: "take-old" }],
    soundtrack_artifact_id: null,
  });
  expect(typeof requests[0].body.client_request_id).toBe("string");
  fireEvent.click(screen.getByRole("button", { name: "Stop export" }));
  await waitFor(() =>
    expect(requests[1].path).toBe("/api/runs/export-one/cancel"),
  );
});
it("uses only a complete mix belonging to the measured saved version", async () => {
  const requests = setup({ sound: true });
  const button = await screen.findByRole("button", { name: "Export film" });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop export" });
  expect(requests[0].body.soundtrack_artifact_id).toBe("full-mix");
});
it.each([
  [{ available: false }, "Renderer not prepared"],
  [{ disabled: true }, "Save your scene edits"],
  [
    { sound: true, measured: false },
    "Create and apply the complete soundtrack",
  ],
  [{ video: true, short: true }, "longer footage"],
  [{ video: true, wrongKind: true }, "Finish the actual media"],
  [{ selectedTake: "deleted-take" }, "Finish the actual media"],
])(
  "does not export an incomplete or unavailable composition: %j",
  async (options, reason) => {
    const requests = setup(options);
    await screen.findByText(new RegExp(reason));
    expect(
      (screen.getByRole("button", { name: "Export film" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Export film" }));
    expect(requests).toHaveLength(0);
  },
);
it("keeps completed MP4 playback and download available on an archived material", async () => {
  setup({ finished: true, readOnly: true });
  const player = await screen.findByLabelText("Exported film");
  expect(player.getAttribute("src")).toBe("/api/artifacts/film-one/file");
  expect(player.hasAttribute("controls")).toBe(true);
  expect(player.hasAttribute("autoplay")).toBe(false);
  const download = screen.getByRole("link", { name: "Download MP4" });
  expect(download.getAttribute("href")).toBe("/api/artifacts/film-one/file");
  expect(download.getAttribute("download")).toBe("story.mp4");
  expect(
    (
      screen.getByRole("button", {
        name: "Export another version",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.getByText(/Restore this material/)).toBeTruthy();
});

it("exports shared visuals with just the original source binding", async () => {
  const requests = setup({ shared: true });
  const button = await screen.findByRole("button", { name: "Export film" });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].body.bindings).toEqual([
    { scene: 0, artifact_id: "take-old" },
  ]);
});
it("blocks a clip that covers its original scene but not a later shared trim window", async () => {
  const requests = setup({ video: true, shared: true, sharedTrim: 5 });
  await screen.findByText(/longer footage/);
  expect(
    (screen.getByRole("button", { name: "Export film" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(requests).toHaveLength(0);
});
