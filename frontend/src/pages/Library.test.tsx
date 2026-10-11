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
import { ArtifactDetail, Library } from "./Library";
import type { Artifact, ArtifactLineage } from "../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const original: Artifact = {
  id: "portrait",
  type: "image",
  mime_type: "image/png",
  original_filename: "source.png",
  size_bytes: 100,
  created_at: "2026-09-28T10:00:00Z",
  run_id: null,
  metadata: {},
  parent_artifact_ids: [],
  title: "",
  notes: "",
  library_updated_at: null,
  trashed_at: null,
};
function mount(path = "/library/portrait") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/library" element={<Library />} />
          <Route path="/library/:id" element={<ArtifactDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("edits annotations, confirms Trash, and restores using each returned version", async () => {
  let row = { ...original };
  const fetch = vi.fn(async (_path: string, init?: RequestInit) => {
    if (init?.method === "PATCH")
      row = {
        ...row,
        ...JSON.parse(String(init.body)),
        library_updated_at: "2026-09-28T11:00:00Z",
      };
    if (init?.method === "DELETE")
      row = {
        ...row,
        trashed_at: "2026-09-28T12:00:00Z",
        library_updated_at: "2026-09-28T12:00:00Z",
      };
    if (init?.method === "POST")
      row = {
        ...row,
        trashed_at: null,
        library_updated_at: "2026-09-28T13:00:00Z",
      };
    if (String(_path).endsWith("/lineage"))
      return {
        ok: true,
        json: async () => ({ id: row.id, sources: [], derived: [] }),
      };
    return { ok: true, json: async () => ({ ...row }) };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
  expect(screen.queryByRole("heading", { name: "Lineage" })).toBeNull();
  expect(
    screen.getByRole("dialog", { name: "Edit artifact details" }),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "My portrait" },
  });
  fireEvent.change(screen.getByLabelText("Notes"), {
    target: { value: "For the avatar" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await screen.findByRole("heading", { name: "My portrait" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/artifacts/portrait",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        expected_updated_at: null,
        title: "My portrait",
        notes: "For the avatar",
      }),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  expect(screen.getByRole("dialog", { name: "Move to Trash?" })).toBeTruthy();
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === "DELETE"),
  ).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  await screen.findByText(/This artifact is in Trash/);
  expect(fetch).toHaveBeenCalledWith(
    "/api/artifacts/portrait",
    expect.objectContaining({
      method: "DELETE",
      body: JSON.stringify({ expected_updated_at: "2026-09-28T11:00:00Z" }),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Restore to Library" }));
  await waitFor(() =>
    expect(screen.queryByText(/This artifact is in Trash/)).toBeNull(),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/artifacts/portrait/restore",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_updated_at: "2026-09-28T12:00:00Z" }),
    }),
  );
});
it("filters and searches the collection and imports WAV through the audio adapter", async () => {
  const fetch = vi.fn(async (_path: string, init?: RequestInit) => ({
    ok: true,
    json: async () =>
      init?.method === "POST"
        ? original
        : String(_path).endsWith("/lineage")
          ? { id: original.id, sources: [], derived: [] }
          : _path.includes("?")
            ? []
            : original,
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/library");
  fireEvent.click(screen.getByRole("button", { name: "Video" }));
  fireEvent.change(screen.getByLabelText("Search Library"), {
    target: { value: "portrait" },
  });
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([path]) =>
          path.includes("kind=video") && path.includes("search=portrait"),
      ),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Trash" }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([path]) => path.includes("view=trash"))).toBe(
      true,
    ),
  );
  fireEvent.change(screen.getByLabelText("Import artifact"), {
    target: { files: [new File(["wav"], "voice.wav", { type: "audio/wav" })] },
  });
  await screen.findByRole("heading", { name: "source.png" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/audio/uploads",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );
});
it("moves through Library artifacts with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { ...original, id: "portrait", title: "Portrait" },
        {
          ...original,
          id: "voiceclip",
          type: "audio",
          title: "Voice take",
          original_filename: "voice.wav",
        },
      ],
    }),
  );
  mount("/library");
  const first = await screen.findByRole("link", {
    name: "Inspect Portrait portrait",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Voice take voicecli",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Library" })).toBeTruthy();
  fireEvent.keyDown(first.closest(".artifact-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".artifact-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
it("shows shared source and derived lineage without inventing a Run", async () => {
  const portrait: Artifact = {
    ...original,
    id: "portrait1",
    title: "Portrait",
  };
  const edited: Artifact = {
    ...original,
    id: "edited01",
    title: "Edited portrait",
    original_filename: "edited.png",
    parent_artifact_ids: ["portrait1"],
    trashed_at: "2026-09-28T12:00:00Z",
  };
  const voice: Artifact = {
    ...original,
    id: "voiceclip",
    type: "audio",
    mime_type: "audio/wav",
    title: "Voice take",
    original_filename: "voice.wav",
  };
  const video: Artifact = {
    ...original,
    id: "avatar01",
    type: "video",
    mime_type: "video/mp4",
    title: "Avatar take",
    original_filename: "avatar.mp4",
    parent_artifact_ids: ["edited01", "voiceclip"],
    metadata: { capability: "avatar.animate" },
  };
  const rows: Record<string, Artifact> = {
    portrait1: portrait,
    edited01: edited,
    voiceclip: voice,
    avatar01: video,
  };
  const lineages: Record<string, ArtifactLineage> = {
    portrait1: { id: "portrait1", sources: [], derived: [edited] },
    edited01: { id: "edited01", sources: [portrait], derived: [video] },
    voiceclip: { id: "voiceclip", sources: [], derived: [video] },
    avatar01: { id: "avatar01", sources: [edited, voice], derived: [] },
  };
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    expect(init?.method ?? "GET").toBe("GET");
    const url = String(path);
    if (url.endsWith("/lineage")) {
      const artifactId = url.split("/")[3];
      return { ok: true, json: async () => lineages[artifactId] };
    }
    const artifactId = url.split("/")[3];
    return { ok: true, json: async () => rows[artifactId] };
  });
  vi.stubGlobal("fetch", fetch);
  mount("/library/avatar01");
  const first = await screen.findByRole("link", {
    name: "Inspect source Edited portrait edited01",
  });
  const second = screen.getByRole("link", {
    name: "Inspect source Voice take voicecli",
  });
  expect(screen.queryByRole("link", { name: /Inspect derived/ })).toBeNull();
  expect(screen.getByText(/· Trash/)).toBeTruthy();
  expect(screen.getByText(/There is no inspectable lineage Run/)).toBeTruthy();
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  fireEvent.keyDown(first.closest(".lineage-strip") as HTMLElement, {
    key: "ArrowRight",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".lineage-strip") as HTMLElement, {
    key: "Enter",
  });
  fireEvent.click(first);
  await screen.findByRole("heading", { name: "Edited portrait" });
  const derived = await screen.findByRole("link", {
    name: "Inspect derived Avatar take avatar01",
  });
  expect(
    screen.getByRole("link", { name: "Inspect source Portrait portrait" }),
  ).toBeTruthy();
  expect(derived.tabIndex).toBe(0);
  expect(derived.getAttribute("href")).toBe("/library/avatar01");
});
