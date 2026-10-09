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
import type { Artifact } from "../api";

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
    return { ok: true, json: async () => ({ ...row }) };
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
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
      init?.method === "POST" ? original : _path.includes("?") ? [] : original,
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
