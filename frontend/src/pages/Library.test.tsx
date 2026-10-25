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

it("updates deleted artifact history after worker completion without refreshing the page", async () => {
  let phase = "";
  let deleted = false;
  const operation = () => ({
    id: "purge-detail",
    status: phase,
    parameters: {
      items: [
        { id: original.id, name: original.original_filename, version: null },
      ],
      scope: "selected",
    },
    metadata: {
      purge_outcomes: deleted ? { portrait: { state: "deleted" } } : {},
    },
  });
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    let value: unknown;
    if (path === "/api/library/purges" && init?.method === "POST") {
      phase = "waiting_for_approval";
      value = operation();
    } else if (path.endsWith("/approval")) {
      phase = "queued";
      value = operation();
    } else if (path === "/api/library/purges")
      value = phase ? [operation()] : [];
    else if (path.endsWith("/lineage"))
      value = { id: original.id, sources: [], derived: [] };
    else
      value = {
        ...original,
        ...(deleted
          ? { purged_at: "2026-10-25T12:00:00Z", purge_run_id: "purge-detail" }
          : {}),
      };
    return { ok: true, json: async () => value };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete permanently portrait" }),
  );
  await screen.findByText("1 artifact");
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter(([path]) => path === "/api/artifacts/portrait")
        .length,
    ).toBeGreaterThan(1),
  );
  deleted = true;
  phase = "succeeded";
  await screen.findByRole(
    "heading",
    { name: "Artifact permanently deleted" },
    { timeout: 4000 },
  );
  expect(screen.queryByRole("img")).toBeNull();
  expect(
    screen.queryByRole("link", { name: "Open full artifact ↗" }),
  ).toBeNull();
  expect(
    screen.getByRole("link", { name: "Inspect deletion" }).getAttribute("href"),
  ).toBe("/runs/purge-detail");
});
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
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit details portrait" }),
  );
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
  fireEvent.click(
    screen.getByRole("button", { name: "Move to Trash portrait" }),
  );
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
  fireEvent.click(
    screen.getByRole("button", { name: "Restore to Library portrait" }),
  );
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
  const grid = first.closest(".artifact-grid") as HTMLElement;
  const cards = grid.querySelectorAll<HTMLElement>("[data-list-index]");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(cards[0].tabIndex).toBe(0);
  expect(cards[1].tabIndex).toBe(-1);
  expect(
    screen.getByRole("button", { name: "Edit details portrait" }).tabIndex,
  ).toBe(0);
  expect(
    screen.getByRole("button", { name: "Edit details voicecli" }).tabIndex,
  ).toBe(-1);
  expect(screen.getByRole("region", { name: "Library" })).toBeTruthy();
  fireEvent.keyDown(grid, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(cards[1].tabIndex).toBe(0);
  expect(document.activeElement).toBe(cards[1]);
  fireEvent.keyDown(grid, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
  expect(cards[0].tabIndex).toBe(0);
});
it("edits and trashes a collection artifact without opening the inspector", async () => {
  let row = {
    ...original,
    title: "Portrait",
    library_updated_at: "2026-10-11T10:00:00Z",
  };
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "PATCH")
      row = {
        ...row,
        ...JSON.parse(String(init.body)),
        library_updated_at: "2026-10-11T11:00:00Z",
      };
    if (init?.method === "DELETE")
      row = {
        ...row,
        trashed_at: "2026-10-11T12:00:00Z",
        library_updated_at: "2026-10-11T12:00:00Z",
      };
    return {
      ok: true,
      json: async () =>
        String(path).includes("?") && !init ? [row] : { ...row },
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount("/library");
  expect(
    await screen.findByRole("heading", {
      name: "Everything you create, in one place.",
    }),
  ).toBeTruthy();
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit details portrait" }),
  );
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Evening study" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/artifacts/portrait",
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
  fireEvent.click(
    screen.getByRole("button", { name: "Move to Trash portrait" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/artifacts/portrait",
      expect.objectContaining({
        method: "DELETE",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T11:00:00Z",
        }),
      }),
    ),
  );
  expect(
    screen.getByRole("heading", {
      name: "Everything you create, in one place.",
    }),
  ).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Lineage" })).toBeNull();
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
it("stages Library images and speech into Avatars without a Run", async () => {
  const voice: Artifact = {
    ...original,
    id: "voiceclip",
    type: "audio",
    mime_type: "audio/wav",
    original_filename: "voice.wav",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      return {
        ok: true,
        json: async () =>
          String(path).endsWith("/lineage")
            ? {
                id: String(path).includes("voiceclip")
                  ? "voiceclip"
                  : "portrait",
                sources: [],
                derived: [],
              }
            : String(path).includes("voiceclip")
              ? voice
              : original,
      };
    }),
  );
  mount("/library/portrait");
  expect(
    (
      await screen.findByRole("link", { name: "Use as portrait portrait" })
    ).getAttribute("href"),
  ).toBe("/avatars?image=portrait");
  cleanup();
  mount("/library/voiceclip");
  expect(
    (
      await screen.findByRole("link", { name: "Use as speech voicecli" })
    ).getAttribute("href"),
  ).toBe("/avatars?audio=voiceclip");
  expect(
    screen
      .getByRole("link", { name: "Use as voice reference" })
      .getAttribute("href"),
  ).toBe("/audio?input=voiceclip");
});
