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
import StudioMaterial from "./StudioMaterial";
import StudioMaterialCreate from "./StudioMaterialCreate";
import { initialDefinition } from "../components/creative/creative-project";
import type {
  StudioMaterial as Material,
  StudioRevision,
} from "./studio-material";

const material: Material = {
  id: "material-one",
  title: "A hidden pattern",
  brief: "Tell a visual story about light.",
  creative_project_id: null,
  options: initialDefinition().defaults,
  version: 2,
  created_at: "2026-11-11T14:00:00Z",
  updated_at: "2026-11-11T14:00:00Z",
  archived_at: null,
};
const revision: StudioRevision = {
  id: "revision-one",
  material_id: material.id,
  parent_revision_id: null,
  source_run_id: "run-one",
  position: 1,
  sources: {},
  project_snapshot: { name: "Learning studio", version: 3 },
  options: material.options,
  brief: material.brief,
  created_at: material.created_at,
  storyboard: {
    title: "A hidden pattern",
    concept: "A coherent visual explanation",
    hook: "What if light holds more than you can see?",
    audio: "voice_music",
    voice_direction: "Warm and clear",
    music_brief: "Restrained cinematic instrumental",
    scenes: [
      {
        purpose: "Reveal the hidden spectrum",
        duration_frames: 120,
        visual_kind: "video",
        visual_brief: "A glass prism rotates in a narrow beam of light.",
        framing: "A slow macro push toward the prism",
        narration: "A small change reveals a hidden pattern.",
        title: "See the hidden pattern",
        eyebrow: "",
        body: "",
        points: [],
        source_artifact_id: null,
        reference_artifact_ids: [],
        layout: "full_bleed",
        media_motion: "auto",
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

function fixture(path = "/studio/materials/material-one", empty = false) {
  let current = structuredClone(material);
  let versions = empty ? [] : [structuredClone(revision)];
  const activity: Record<string, unknown>[] = [];
  const requests: {
    path: string;
    method: string;
    body: Record<string, unknown>;
  }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const json = (value: unknown, status = 200) =>
        new Response(JSON.stringify(value), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      if (!init?.method || init.method === "GET") {
        if (url.pathname.endsWith("/activity")) return json(activity);
        if (url.pathname.endsWith("/revisions/revision-old"))
          return json({
            ...revision,
            id: "revision-old",
            position: 1,
            storyboard: {
              ...revision.storyboard,
              title: "An earlier direction",
            },
          });
        if (url.pathname.includes("/revisions/"))
          return json(
            versions.find((r) => url.pathname.endsWith(r.id)) ?? {},
            200,
          );
        if (url.pathname.endsWith("/revisions")) return json(versions);
        if (url.pathname === "/api/creative/projects/brand-one")
          return json({
            ...initialDefinition(),
            id: "brand-one",
            name: "Learning studio",
            defaults: {
              format: "presentation",
              aspect: "landscape",
              duration_seconds: 45,
              audio: "music",
            },
          });
        if (url.pathname.endsWith("/model-catalog"))
          return json({
            providers: [
              {
                key: "local-openai-compatible",
                name: "Local AI",
                location: "local",
                enabled: true,
                discovered: true,
                error: "",
              },
            ],
            models: [
              {
                model_ref: "large-model",
                provider_key: "local-openai-compatible",
                provider_name: "Local AI",
                model_key: "llamacpp:large",
                display_name: "My local director",
                location: "local",
                runtime_kind: "llama.cpp",
                availability: "ready",
                unavailable_reason: "",
                config_version: "1",
                endpoint_host: "local",
                modalities: ["text"],
              },
            ],
          });
        if (url.pathname === "/api/studio/materials/material-one")
          return json(current);
        if (url.pathname === "/api/studio/materials") return json([current]);
        throw new Error(`Unexpected GET ${url.pathname}`);
      }
      const body = JSON.parse(String(init.body ?? "{}"));
      requests.push({ path: url.pathname, method: init.method, body });
      if (url.pathname.endsWith("/plan")) {
        activity.push({
          id: "plan-new",
          task_id: "task-new",
          status: "queued",
          created_at: material.created_at,
          parameters: {},
        });
        return json(activity[0], 202);
      }
      if (url.pathname.endsWith("/revisions")) {
        const saved = {
          ...revision,
          id: "revision-two",
          parent_revision_id: revision.id,
          position: 2,
          storyboard: body.storyboard,
        };
        versions = [saved as StudioRevision, ...versions];
        current = { ...current, version: 3 };
        return json(saved, 201);
      }
      if (url.pathname.endsWith("/cancel")) {
        activity[0].status = "cancel_requested";
        return json(activity[0]);
      }
      if (init.method === "PATCH") {
        current = {
          ...current,
          archived_at: "2026-11-11T15:00:00Z",
          version: current.version + 1,
        };
        return json(current);
      }
      if (url.pathname === "/api/studio/materials") {
        current = { ...current, ...body, id: "material-one", version: 1 };
        return json(current, 201);
      }
      throw new Error(`Unexpected ${init.method} ${url.pathname}`);
    }),
  );
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/studio/materials/new"
            element={<StudioMaterialCreate />}
          />
          <Route path="/studio/materials/:id" element={<StudioMaterial />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return Object.assign(requests, {
    completePlan: async () => {
      versions = [
        {
          ...structuredClone(revision),
          id: "revision-two",
          position: 2,
          source_run_id: "plan-new",
        },
        ...versions,
      ];
      activity[0].status = "succeeded";
      activity[0].metadata = { studio_revision_id: "revision-two" };
      await cache.invalidateQueries({ queryKey: ["studio-activity"] });
    },
  });
}

it("creates a material with the selected project's format and sound defaults", async () => {
  const requests = fixture("/studio/materials/new?project=brand-one", true);
  const brief = await screen.findByLabelText("Your brief");
  expect((screen.getByLabelText("Canvas") as HTMLSelectElement).value).toBe(
    "landscape",
  );
  expect((screen.getByLabelText("Sound") as HTMLSelectElement).value).toBe(
    "music",
  );
  fireEvent.change(brief, { target: { value: "An original visual lesson" } });
  fireEvent.click(screen.getByRole("button", { name: "Create material" }));
  await screen.findByRole("heading", { name: "Your storyboard" });
  expect(requests[0]).toMatchObject({
    method: "POST",
    path: "/api/studio/materials",
    body: {
      creative_project_id: "brand-one",
      options: {
        format: "presentation",
        aspect: "landscape",
        audio: "music",
        duration_seconds: 45,
      },
    },
  });
  expect(requests[0].body.client_request_id).toMatch(/^[a-f0-9-]{36}$/);
});

it("plans through the selected local llama.cpp model and exposes Stop without invented output", async () => {
  const requests = fixture("/studio/materials/material-one", true);
  const prepare = await screen.findByRole("button", {
    name: "Prepare storyboard",
  });
  await waitFor(() =>
    expect((prepare as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Additional direction"), {
    target: { value: "A strong visual opening" },
  });
  fireEvent.click(prepare);
  await screen.findByText("Developing your story");
  expect(requests[0].body).toMatchObject({
    model: "llamacpp:large",
    expected_version: 2,
    feedback: "A strong visual opening",
  });
  expect(screen.queryByRole("video")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(requests.some((r) => r.path === "/api/runs/plan-new/cancel")).toBe(
      true,
    ),
  );
});

it("edits one scene into a new immutable version, keeping the original visible", async () => {
  const requests = fixture();
  await screen.findByText("Reveal the hidden spectrum");
  fireEvent.click(screen.getByText("Edit this shot"));
  fireEvent.change(screen.getByLabelText("Spoken words"), {
    target: { value: "A clearer, shorter narration." },
  });
  expect(
    (
      screen.getByRole("button", {
        name: "Plan a new version",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
  await screen.findByText("Version 2 saved");
  expect(requests[0]).toMatchObject({
    path: "/api/studio/materials/material-one/revisions",
    body: {
      expected_version: 2,
      parent_revision_id: "revision-one",
      storyboard: {
        scenes: [
          { narration: "A clearer, shorter narration.", visual_kind: "video" },
        ],
      },
    },
  });
  expect(screen.getAllByRole("option", { name: /Version/ })).toHaveLength(2);
});

it("archives without deleting the storyboard and offers restore", async () => {
  const requests = fixture();
  await screen.findByText("Reveal the hidden spectrum");
  fireEvent.click(screen.getByRole("button", { name: "Archive material" }));
  await screen.findByRole("button", { name: "Restore material" });
  expect(requests[0].body).toMatchObject({
    expected_version: 2,
    archived: true,
  });
  expect(screen.getByText("Reveal the hidden spectrum")).toBeTruthy();
});

it("opens the completed requested version instead of leaving the previous take selected", async () => {
  const requests = fixture();
  const button = await screen.findByRole("button", {
    name: "Plan a new version",
  });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByText("Developing your story");
  await requests.completePlan();
  await screen.findByText("Version 2 saved");
  expect(
    (
      screen.getByRole("combobox", {
        name: "Storyboard version",
      }) as HTMLSelectElement
    ).value,
  ).toBe("revision-two");
  expect(screen.getAllByRole("option", { name: /Version/ })).toHaveLength(2);
});

it("opens a saved version by its exact link even outside the first history page", async () => {
  fixture("/studio/materials/material-one?revision=revision-old");
  await screen.findByRole("heading", { name: "An earlier direction" });
  expect(
    (
      screen.getByRole("combobox", {
        name: "Storyboard version",
      }) as HTMLSelectElement
    ).value,
  ).toBe("revision-old");
});
