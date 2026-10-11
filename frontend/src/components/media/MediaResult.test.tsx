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
import MediaResult from "./MediaResult";
import type { Artifact, ArtifactLineage, Run } from "../../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const portrait: Artifact = {
  id: "portrait1",
  type: "image",
  mime_type: "image/png",
  original_filename: "portrait.png",
  title: "Portrait",
  size_bytes: 10,
  created_at: "2026-09-28T10:00:00Z",
  run_id: null,
  parent_artifact_ids: [],
  metadata: {},
};
const voice: Artifact = {
  ...portrait,
  id: "voiceclip",
  type: "audio",
  mime_type: "audio/wav",
  original_filename: "voice.wav",
  title: "Voice take",
};
const video: Artifact = {
  ...portrait,
  id: "avatar01",
  type: "video",
  mime_type: "video/mp4",
  original_filename: "avatar.mp4",
  title: "Avatar take",
  parent_artifact_ids: ["portrait1", "voiceclip"],
  metadata: { capability: "avatar.animate" },
};

function mount(run: Run, lineage: ArtifactLineage, artifact: Artifact) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      const url = String(path);
      return {
        ok: true,
        json: async () =>
          url.endsWith("/lineage")
            ? lineage
            : url.includes("/artifacts?")
              ? [artifact]
              : run,
      };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <MediaResult
          kind={
            artifact.type === "audio"
              ? "audio"
              : artifact.type === "image"
                ? "image"
                : "video"
          }
          runId={run.id}
          run={run}
          error={null}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows avatar sources in the workspace without inventing a Run", async () => {
  mount(
    { id: "done", status: "succeeded" } as Run,
    { id: "avatar01", sources: [portrait, voice], derived: [] },
    video,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect source Portrait portrait",
  });
  const second = screen.getByRole("link", {
    name: "Inspect source Voice take voicecli",
  });
  expect(screen.getByText(/There is no inspectable lineage Run/)).toBeTruthy();
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  fireEvent.keyDown(first.closest(".lineage-strip") as HTMLElement, {
    key: "ArrowRight",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(second.getAttribute("href")).toBe("/library/voiceclip");
});

it("shows speech source lineage beside the generated WAV", async () => {
  const speech: Artifact = {
    ...voice,
    id: "spoken01",
    title: "Spoken line",
    parent_artifact_ids: ["voiceclip"],
  };
  mount(
    { id: "speech", status: "succeeded" } as Run,
    { id: "spoken01", sources: [voice], derived: [] },
    speech,
  );
  const source = await screen.findByRole("link", {
    name: "Inspect source Voice take voicecli",
  });
  expect(source.getAttribute("href")).toBe("/library/voiceclip");
  expect(screen.getByLabelText("Generated audio")).toBeTruthy();
});

it("stops a queued image run from the workspace", async () => {
  const fetch = vi.fn(async (_path: string, init?: RequestInit) => ({
    ok: true,
    json: async () =>
      init?.method === "POST" ? {} : { id: "run-id", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <MediaResult
          kind="image"
          runId="run-id"
          run={{ id: "run-id", status: "queued" } as Run}
          error={null}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/run-id/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

it("shows a generated image with source lineage in the workspace", async () => {
  const edited: Artifact = {
    ...portrait,
    id: "edited01",
    title: "Dusk room",
    parent_artifact_ids: ["portrait1"],
    metadata: { mode: "img2img" },
  };
  mount(
    { id: "photo", status: "succeeded" } as Run,
    { id: "edited01", sources: [portrait], derived: [] },
    edited,
  );
  const image = await screen.findByAltText("Generated image");
  expect(image.getAttribute("src")).toBe("/api/artifacts/edited01/file");
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/edited01");
  const source = await screen.findByRole("link", {
    name: "Inspect source Portrait portrait",
  });
  expect(source.getAttribute("href")).toBe("/library/portrait1");
  expect(screen.getByText(/There is no inspectable lineage Run/)).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Edit edited01" }).getAttribute("href"),
  ).toBe("/images?mode=img2img&input=edited01&run=photo");
  expect(
    screen
      .getByRole("link", { name: "Recompose edited01" })
      .getAttribute("href"),
  ).toBe("/images?mode=recompose&input=edited01&run=photo");
  expect(
    screen.getByRole("link", { name: "Upscale edited01" }).getAttribute("href"),
  ).toBe("/images?mode=upscale&input=edited01&run=photo");
  expect(
    screen
      .getByRole("link", { name: "Use as portrait edited01" })
      .getAttribute("href"),
  ).toBe("/avatars?image=edited01");
});

it("reuses generated speech as the next voice without inventing a Run", async () => {
  const speech: Artifact = {
    ...voice,
    id: "spoken01",
    title: "Spoken line",
    parent_artifact_ids: ["voiceclip"],
  };
  mount(
    { id: "speech", status: "succeeded" } as Run,
    { id: "spoken01", sources: [voice], derived: [] },
    speech,
  );
  expect(
    (
      await screen.findByRole("link", {
        name: "Use as voice reference spoken01",
      })
    ).getAttribute("href"),
  ).toBe("/audio?input=spoken01&run=speech");
  expect(
    screen
      .getByRole("link", { name: "Use as speech spoken01" })
      .getAttribute("href"),
  ).toBe("/avatars?audio=spoken01");
});

it("edits Library details on a finished image without queueing a Run", async () => {
  const edited: Artifact = {
    ...portrait,
    id: "edited01",
    title: "Dusk room",
    notes: "",
    library_updated_at: "2026-10-11T10:00:00Z",
  };
  const run = { id: "photo", status: "succeeded" } as Run;
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    const url = String(path);
    if (init?.method === "PATCH") {
      return {
        ok: true,
        json: async () => ({
          ...edited,
          title: "Evening study",
          library_updated_at: "2026-10-11T11:00:00Z",
        }),
      };
    }
    expect(init?.method ?? "GET").toBe("GET");
    return {
      ok: true,
      json: async () =>
        url.endsWith("/lineage")
          ? { id: edited.id, sources: [], derived: [] }
          : url.includes("/artifacts?")
            ? [edited]
            : run,
    };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <MediaResult kind="image" runId={run.id} run={run} error={null} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Dusk room")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Edit details edited01" }),
  );
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Evening study" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/artifacts/edited01",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
          title: "Evening study",
          notes: "",
        }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every(
      (call) =>
        !String(call[0]).includes("/runs/") &&
        (call[1]?.method ?? "GET") !== "POST",
    ),
  ).toBe(true);
});
