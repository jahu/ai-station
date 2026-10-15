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
import { Memory, MemoryDetail } from "./Memory";

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
          <Route path="/agents/:id" element={<h1>Agent definition</h1>} />
          <Route path="/projects/:id" element={<h1>Project details</h1>} />
          <Route path="/runs" element={<h1>Tagged Runs</h1>} />
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

it("opens tagged agent Runs from agent-scoped memory without Enable or Run now", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method
        ? { id: "unexpected" }
        : {
            ...entry,
            scope: "agent",
            scope_id: "agentone",
            memory_type: "observation",
            content: "Workstation was healthy",
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    (
      await screen.findByRole("link", { name: "Open agent agentone" })
    ).getAttribute("href"),
  ).toBe("/agents/agentone");
  expect(
    screen
      .getByRole("link", { name: "View agent runs agentone" })
      .getAttribute("href"),
  ).toBe("/runs?agent_id=agentone");
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  fireEvent.click(
    screen.getByRole("link", { name: "View agent runs agentone" }),
  );
  await screen.findByRole("heading", { name: "Tagged Runs" });
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
});

it("opens tagged project Runs from project-scoped memory without starting a coding Run", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method
        ? { id: "unexpected" }
        : {
            ...entry,
            scope: "project",
            scope_id: "project-1",
            memory_type: "project_context",
            content: "Use the owned worktree",
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    (
      await screen.findByRole("link", { name: "Open project project-1" })
    ).getAttribute("href"),
  ).toBe("/projects/project-1");
  expect(
    screen
      .getByRole("link", { name: "View project runs project-1" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1");
  expect(screen.queryByRole("link", { name: /Scoped project/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  fireEvent.click(
    screen.getByRole("link", { name: "View project runs project-1" }),
  );
  await screen.findByRole("heading", { name: "Tagged Runs" });
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
});

it("keeps tagged Runs off global memory", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => entry,
    })),
  );
  mount();
  await screen.findByDisplayValue(entry.content);
  expect(screen.queryByRole("link", { name: /Open agent/ })).toBeNull();
  expect(screen.queryByRole("link", { name: /Open project/ })).toBeNull();
  expect(screen.queryByRole("link", { name: /View .* runs/ })).toBeNull();
});

it("moves through Memory entries with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        String(url).includes("/embeddings/setup")
          ? {
              configured: false,
              endpoint: "",
              model: "",
              dimension: null,
              indexed_count: 0,
              memory_count: 0,
              last_health_run_id: null,
              last_index_run_id: null,
            }
          : [
              {
                ...entry,
                id: "mem-one1",
                content: "Prefer concise answers",
                memory_type: "preference",
              },
              {
                ...entry,
                id: "mem-two2",
                content: "Use the owned worktree",
                memory_type: "procedure",
                pinned: false,
              },
            ],
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Memory />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect preference mem-one1",
  });
  const second = screen.getByRole("link", {
    name: "Inspect procedure mem-two2",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Memory" })).toBeTruthy();
  fireEvent.keyDown(first.closest(".memory-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".memory-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through pin and enabled flags without inventing a Run", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => entry,
    })),
  );
  mount();
  const pinned = await screen.findByLabelText("Memory pinned");
  const enabled = screen.getByLabelText("Memory enabled");
  expect(pinned.tabIndex).toBe(0);
  expect(enabled.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable memory-flag Run/),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Pinned context/i,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  fireEvent.keyDown(pinned.closest(".memory-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Pinned context/i,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
  fireEvent.keyDown(pinned.closest(".memory-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(enabled.tabIndex).toBe(0);
  expect(pinned.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(enabled);
  fireEvent.keyDown(enabled.closest(".memory-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (screen.getByRole("checkbox", { name: /Enabled/i }) as HTMLInputElement)
      .checked,
  ).toBe(false);
});
