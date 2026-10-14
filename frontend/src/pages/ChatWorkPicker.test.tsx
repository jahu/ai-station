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
import ChatWorkPicker from "./ChatWorkPicker";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(fail = false) {
  const requests: { url: string; method?: string; body?: unknown }[] = [];
  const onSelected = vi.fn();
  const onBusyChange = vi.fn();
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  cache.setQueryData(["conversation", "chat"], {
    id: "chat",
    settings_version: 3,
    messages: [],
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      requests.push({
        url,
        method: init?.method,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (init?.method === "PUT")
        return {
          ok: !fail,
          status: fail ? 409 : 200,
          json: async () =>
            fail
              ? { detail: "Coding task changed; reload before selecting" }
              : { work_context: { task_id: "task" }, settings_version: 4 },
        };
      return {
        ok: true,
        json: async () => [
          {
            id: "task",
            title: "Build site",
            project_name: "Website",
            status: "succeeded",
            latest_proposal_id: "source",
          },
        ],
      };
    }),
  );
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <ChatWorkPicker
          conversationId="chat"
          settingsVersion={3}
          busy={false}
          onBusyChange={onBusyChange}
          onSelected={onSelected}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { requests, cache, onSelected, onBusyChange };
}

it("fetches only when opened and selecting a task queues no execution", async () => {
  const state = mount();
  expect(state.requests).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Choose coding task" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Continue Build site in Website",
    }),
  );
  await waitFor(() => expect(state.onSelected).toHaveBeenCalledOnce());
  expect(state.requests.filter((r) => r.method)).toEqual([
    {
      url: "/api/chat/conversations/chat/work-context",
      method: "PUT",
      body: {
        task_id: "task",
        expected_run_id: "source",
        expected_settings_version: 3,
      },
    },
  ]);
  expect(state.cache.getQueryData(["conversation", "chat"])).toMatchObject({
    settings_version: 4,
    work_context: { task_id: "task" },
  });
  expect(state.onBusyChange.mock.calls).toEqual([[true], [false]]);
  expect(screen.queryByText("Continue an existing workspace")).toBeNull();
});

it("preserves the picker after a stale-selection conflict without granting execution", async () => {
  const state = mount(true);
  fireEvent.click(screen.getByRole("button", { name: "Choose coding task" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Continue Build site in Website",
    }),
  );
  await screen.findByText("Coding task changed; reload before selecting");
  expect(state.onSelected).not.toHaveBeenCalled();
  expect(state.cache.getQueryData(["conversation", "chat"])).toMatchObject({
    settings_version: 3,
  });
  expect(screen.getByText("Continue an existing workspace")).toBeTruthy();
});

it("explicitly selects General Work and searches task/project names without a Run", async () => {
  const state = mount();
  fireEvent.click(screen.getByRole("button", { name: "Choose coding task" }));
  await screen.findByRole("button", { name: "Continue Build site in Website" });
  fireEvent.change(
    screen.getByRole("textbox", { name: "Find coding task or project" }),
    { target: { value: "Website" } },
  );
  await waitFor(() =>
    expect(state.requests.some((r) => r.url.includes("q=Website"))).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "General Work" }));
  await waitFor(() => expect(state.onSelected).toHaveBeenCalledOnce());
  expect(state.requests.filter((r) => r.method)[0].body).toEqual({
    task_id: null,
    expected_run_id: null,
    expected_settings_version: 3,
  });
});

it("Escape closes the task picker and returns keyboard focus without selecting", async () => {
  const state = mount();
  const trigger = screen.getByRole("button", { name: "Choose coding task" });
  fireEvent.click(trigger);
  await screen.findByRole("button", { name: "Continue Build site in Website" });
  const search = screen.getByRole("textbox", {
    name: "Find coding task or project",
  });
  search.focus();
  fireEvent.keyDown(search, { key: "Escape" });
  expect(
    screen.queryByRole("textbox", { name: "Find coding task or project" }),
  ).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(state.requests.every((r) => !r.method)).toBe(true);
});
