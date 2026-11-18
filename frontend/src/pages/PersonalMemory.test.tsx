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
import PersonalMemory, { MemorySources } from "./PersonalMemory";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(children: React.ReactNode) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>,
  );
}
const initial = { use: true, learn: false, revision: 4, recent_runs: [] };

it("keeps automatic learning optional and saves the current settings revision", async () => {
  const fetch = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "PUT"
        ? { ...initial, learn: true, revision: 5 }
        : initial,
  }));
  vi.stubGlobal("fetch", fetch);
  mount(<PersonalMemory />);
  const learn = await screen.findByRole("checkbox", {
    name: /Learn from conversations/,
  });
  expect((learn as HTMLInputElement).checked).toBe(false);
  expect(
    (
      screen.getByRole("button", {
        name: "Learn from earlier chats",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(learn);
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([, options]) => options?.method === "PUT"),
    ).toBe(true),
  );
  const call = fetch.mock.calls.find(
    ([, options]) => options?.method === "PUT",
  )!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    use: true,
    learn: true,
    expected_revision: 4,
  });
});

it("opens compact controls in an accessible dialog and supports per-chat opt-out", async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => initial }));
  vi.stubGlobal("fetch", fetch);
  mount(<PersonalMemory compact conversationId="chat-a" autoSummary enabled />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Personal memory: saved only" }),
  );
  await screen.findByRole("dialog");
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Allow memory in this conversation/ }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/chat/conversations/chat-a/context",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ auto_summary: true, personal_memory: false }),
      }),
    ),
  );
  expect(
    screen
      .getByRole("link", { name: /Review and manage memories/ })
      .getAttribute("href"),
  ).toBe("/memory");
  fireEvent.click(
    screen.getByRole("button", { name: "Close memory settings" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("does not turn on learning when use of memories is disabled", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ ...initial, use: false }),
    })),
  );
  mount(<PersonalMemory />);
  const learn = await screen.findByRole("checkbox", {
    name: /Learn from conversations/,
  });
  expect((learn as HTMLInputElement).disabled).toBe(true);
});

it("offers inspectable memory sources without expanding them by default", () => {
  mount(
    <MemorySources
      value={{
        method: "profile+lexical+semantic",
        run_id: "recall-a",
        sources: [{ id: "name-a", content: "Your name is Alex" }],
      }}
    />,
  );
  expect(screen.getByText("Used 1 saved memory").closest("details")?.open).toBe(
    false,
  );
  expect(
    screen
      .getByRole("link", { name: "Your name is Alex", hidden: true })
      .getAttribute("href"),
  ).toBe("/memory/name-a");
});
