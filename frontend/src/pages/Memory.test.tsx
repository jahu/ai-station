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
import { MemoryDetail } from "./Memory";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const entry = {
  id: "saved",
  scope: "global",
  scope_id: "",
  content: "Prefer concise answers",
  memory_type: "preference",
  tags: [],
  confidence: null,
  pinned: true,
  enabled: true,
  created_at: "2026-09-25T10:00:00Z",
  updated_at: "2026-09-25T10:00:00Z",
};
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/memory/saved"]}>
        <Routes>
          <Route path="/memory/:id" element={<MemoryDetail />} />
          <Route path="/memory" element={<h1>Memory list</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("keeps edits on conflict and never silently overwrites a newer memory", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: !options,
    json: async () =>
      options ? { detail: "Memory changed. Reload before saving." } : entry,
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByDisplayValue(entry.content);
  fireEvent.change(screen.getByLabelText("Content"), {
    target: { value: "My unsaved revision" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save memory" }));
  await screen.findByText("Memory changed. Reload before saving.");
  expect((screen.getByLabelText("Content") as HTMLTextAreaElement).value).toBe(
    "My unsaved revision",
  );
  const options = fetch.mock.calls.find(
    (call) => call[1]?.method === "PUT",
  )![1]!;
  expect(JSON.parse(options.body as string)).toMatchObject({
    content: "My unsaved revision",
    expected_updated_at: entry.updated_at,
  });
});

it("requires confirmation before deletion and handles the empty 204 response", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) =>
    options
      ? { ok: true, status: 204 }
      : { ok: true, status: 200, json: async () => entry },
  );
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Delete memory…" }),
  );
  expect(fetch.mock.calls.filter((call) => call[1])).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Keep memory" }));
  expect(fetch.mock.calls.filter((call) => call[1])).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Delete memory…" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Permanently delete memory" }),
  );
  await screen.findByRole("heading", { name: "Memory list" });
  await waitFor(() =>
    expect(fetch.mock.calls.filter((call) => call[1])).toHaveLength(1),
  );
});
