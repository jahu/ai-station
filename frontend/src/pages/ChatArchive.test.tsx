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
import Chat from "./Chat";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
function mount({ archived = false, fail = false } = {}) {
  let row = {
    id: "conversation",
    title: "Saved conversation",
    execution_mode: "chat",
    settings_version: 1,
    archived_at: archived ? "2026-10-15T00:00:00Z" : null,
    provider: "local-openai-compatible",
    model: "test",
    system_prompt: "",
    temperature: 0.7,
    max_tokens: 2048,
    updated_at: "2026-10-15T00:00:00Z",
    messages: [
      {
        id: "message",
        role: "user",
        content: "Keep this message",
        metadata: {},
        run_id: null,
        run_status: null,
        error_message: "",
        created_at: "2026-10-15T00:00:00Z",
      },
    ],
    active_run: null,
    summary: null,
    summary_update: null,
    auto_summary: false,
  };
  const requests: { path: string; method?: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      requests.push({
        path,
        method: init?.method,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (path.endsWith("/archive") && init?.method === "PUT") {
        if (fail)
          return {
            ok: false,
            status: 409,
            json: async () => ({
              detail: "Conversation settings changed; reload",
            }),
          };
        const value = JSON.parse(String(init.body));
        row = {
          ...row,
          archived_at: value.archived ? "2026-10-15T01:00:00Z" : null,
          settings_version: row.settings_version + 1,
        };
      }
      const provider = {
        key: "local-openai-compatible",
        name: "Local",
        builtin: true,
        enabled: true,
        location: "local",
        models: ["test"],
        secret_source: "none",
        secret_present: false,
      };
      let value: unknown = [];
      if (path.includes("/chat/conversations/conversation")) value = row;
      else if (path.includes("/chat/conversations")) value = [row];
      else if (path.endsWith("/chat/providers")) value = [provider];
      else if (path.includes("/chat/providers/")) value = provider;
      else if (path.endsWith("/llama")) value = { models: [], instances: [] };
      else if (path.endsWith("/hardware")) value = { gpus: [] };
      return { ok: true, json: async () => value };
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
      <MemoryRouter initialEntries={["/chat/conversation"]}>
        <Routes>
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return requests;
}
it("archives and restores without losing messages or sending work", async () => {
  const requests = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Archive conversation" }),
  );
  const restore = await screen.findByRole("button", {
    name: "Restore conversation",
  });
  expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
  expect(screen.getByText("Keep this message")).toBeTruthy();
  expect(requests.find((r) => r.method === "PUT")?.body).toEqual({
    archived: true,
    expected_settings_version: 1,
  });
  fireEvent.click(restore);
  await screen.findByRole("textbox", { name: "Message" });
  expect(requests.filter((r) => r.method === "PUT")[1].body).toEqual({
    archived: false,
    expected_settings_version: 2,
  });
  expect(requests.some((r) => r.method === "POST")).toBe(false);
});
it("preserves read-only detail when restoration fails", async () => {
  const requests = mount({ archived: true, fail: true });
  fireEvent.click(
    await screen.findByRole("button", { name: "Restore conversation" }),
  );
  await screen.findByText(/Conversation settings changed/);
  expect(screen.getByText("Keep this message")).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
  expect(requests.some((r) => r.method === "POST")).toBe(false);
});
it("searches archived history without changing or restoring the conversation", async () => {
  const requests = mount({ archived: true });
  await screen.findByRole("button", { name: "Restore conversation" });
  fireEvent.change(
    screen.getByRole("combobox", { name: "Conversation history" }),
    { target: { value: "archived" } },
  );
  fireEvent.change(
    screen.getByRole("searchbox", { name: "Search conversations" }),
    { target: { value: "meeting" } },
  );
  await waitFor(() =>
    expect(
      requests.some(
        (r) => r.path.includes("archived=true") && r.path.includes("q=meeting"),
      ),
    ).toBe(true),
  );
  expect(requests.some((r) => r.method)).toBe(false);
});

it("keeps conversation controls out of the transcript and opens them without writes", async () => {
  const requests = mount();
  await screen.findByText("Keep this message");
  expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Conversation options" }));
  expect(
    screen.getByRole("dialog", { name: "Conversation options" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByText("Conversation settings", { exact: true }));
  expect(screen.getByRole("button", { name: "Save settings" })).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Close conversation options" }),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Recent conversations" }));
  expect(
    screen.getByRole("dialog", { name: "Recent conversations" }),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Close conversation history" }),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(requests.some((r) => r.method)).toBe(false);
});
